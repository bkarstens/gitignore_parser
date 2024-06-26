"""Gitignore parser for Python."""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Iterable, Optional, overload

__all__ = [
    "IgnoreRule",
    "GitignoreMatcher",
    "parse_gitignore",
    "parse_gitignore_file",
    "parse_gitignore_lines",
    "rule_from_pattern",
]

# %%
GITIGNORE_PATTERN = re.compile(
    # a forward slash
    r"(?P<separator>\/)|"
    # multiple asterisks only next to separators
    r"(?P<star_star>(?:^|(?<=\/))\*{2,}(?:$|(?=\/)))|"
    # all other asterisks
    r"(?P<star>\*+)|"
    # a question mark
    r"(?P<question_mark>\?)|"
    # square brackets around characters
    r"(?P<bracket_expression>\[(?:\\.|[^\\])+\])|"
    # backslash followed by any char. Assuming escaped char.
    r"(?P<escaped_char>\\.)|"
    # not a space, slash, asterisk, question mark, opening or closing square
    # brackets, newline, or backslash
    r"(?P<name_piece>[^ \/\*\?\[\]\n\\]+)|"
    # space characters
    r"(?P<spaces>\s+)|"
    # something went wrong; catch all
    r"(?P<error>.+)",
    re.MULTILINE,
)

# %%


@dataclass(frozen=True)
class IgnoreRule:
    """Class representing a single rule parsed from a .ignore file."""

    pattern: str  # the .gitignore pattern
    source: tuple[str, int]  # (file, line), for reporting

    regex: str  # the regex string of the rule
    dir_only_regex: str  # the regex to use if the comparing path is a dir

    negation: bool  # if the rule is a negation of previous rules
    directory_only: bool  # if the pattern has special regex when dir

    def __str__(self) -> str:
        """Return string representation (user friendly) of the rule."""
        return self.pattern


# The character `?` matches any one character except `/`.
QUESTION_MARK_REGEX = "[^/]"
# An asterisk `*` matches anything except a slash.
STAR_REGEX = "[^/]*"
STAR_STAR_REGEX = ".*"
MATCH_NOTHING = IgnoreRule("", ("None", 0), "a^", "a^", False, False)
# %%


class GitignoreMatcher:
    """Class representing all rules from a .ignore file."""

    def __init__(self, rules: Iterable[IgnoreRule], honor_directory_only: bool) -> None:
        """Create a GitignoreMatcher object from the given rules.

        Args:
            rules (Iterable[IgnoreRule]): Iterable of rules
            honor_directory_only (bool): False assumes paths not ending with a
            slash are not dirs. True verifies if they are dirs
        """
        rules = iter(rules)
        # negation as the first rule(s) does nothing. skip them
        first_rule = next((rule for rule in rules if not rule.negation), MATCH_NOTHING)
        pattern = first_rule.regex
        dir_only_pattern = first_rule.dir_only_regex
        dir_only_rules = first_rule.directory_only
        self.rules = [first_rule]

        for rule in rules:
            self.rules.append(rule)
            dir_only_rules |= rule.directory_only
            if rule.negation:
                # $ needed for correct dir only negation
                pattern = f"(?!{rule.regex}$)(?:{pattern})"
                dir_only_pattern = f"(?!{rule.dir_only_regex}$)" f"(?:{dir_only_pattern})"
            else:
                pattern = f"{pattern}|{rule.regex}"
                dir_only_pattern = f"{dir_only_pattern}|{rule.dir_only_regex}"

        self.regex = re.compile(pattern)
        self.honor_directory_only = honor_directory_only and dir_only_rules
        if self.honor_directory_only:
            self.dir_only_regex = re.compile(dir_only_pattern)

    def _call(self, path: str | Path) -> bool:
        """Check if given path should be ignored.

        Args:
            path (str | Path): The path to check.

        Returns:
            bool: True if path should be ignored, else False.
        """
        trailing_slash = ""
        if isinstance(path, str):
            if path.endswith(("/", "\\")):
                trailing_slash = "/"
            path = Path(path)

        if self.honor_directory_only and (trailing_slash or path.is_dir()):
            return self.dir_only_regex.fullmatch(path.as_posix()) is not None
        return self.regex.fullmatch(path.as_posix() + trailing_slash) is not None

    @overload
    def __call__(self, path: str | Path) -> bool:
        ...

    @overload
    def __call__(self, paths: Iterable[str | Path]) -> list[str | Path]:
        ...

    def __call__(self, path_or_paths: str | Path | Iterable[str | Path]) -> bool | list[str | Path]:
        """Check if the given path or paths should be ignored.

        Args:
            path_or_paths (str | Path | Iterable[str | Path]): the
            path or paths to be checked.

        Returns:
            bool | list[str | Path]: if the path is ignored, or the
            list of ignored paths.
        """
        if isinstance(path_or_paths, (str, Path)):
            return self._call(path_or_paths)
        return [path for path in path_or_paths if self._call(path)]

    match = __call__

    def match_iter(self, paths: Iterable[str | Path]) -> Generator[str | Path, None, None]:
        """Check if the given paths should be ignored [Generator].

        Args:
            paths (Iterable[str | Path]): The paths to be checked.

        Yields:
            Generator[str | Path, None, None]: Each matching path.
        """
        return (path for path in paths if self._call(path))

    def __repr__(self) -> str:
        """Return string representation (developer friendly) of the rules."""
        return f"GitignoreMatcher(rules={self.rules!r})"


# %%


def parse_gitignore(
    gitignore_path: str | Path, base_dir: str | Path = "", honor_directory_only: bool = False
) -> GitignoreMatcher:
    """Parse a gitignore file."""
    if not base_dir:
        base_dir = Path(gitignore_path).parent
    with open(gitignore_path, encoding="utf-8") as gitignore_file:
        generator = _rule_generator(gitignore_file, base_dir, str(gitignore_path))
        return GitignoreMatcher(generator, honor_directory_only)


parse_gitignore_file = parse_gitignore


def parse_gitignore_lines(
    gitignore_lines: list[str], full_path: str | Path, source: str = "", honor_directory_only: bool = False
) -> GitignoreMatcher:
    """Parse a list of lines matching gitignore syntax."""
    base_dir = Path(full_path).parent
    generator = _rule_generator(gitignore_lines, base_dir, source)

    return GitignoreMatcher(generator, honor_directory_only)


def _rule_generator(
    gitignore_lines: Iterable[str], base_dir: str | Path, source: str
) -> Generator[IgnoreRule, None, None]:
    for line_number, line in enumerate(gitignore_lines, start=1):
        ignore_rule = rule_from_pattern(pattern=line, base_path=base_dir, source=(source, line_number))
        if ignore_rule:
            yield ignore_rule


def rule_from_pattern(
    pattern: str, base_path: str | Path, source: tuple[str, int] = ("Unknown", 0)
) -> Optional[IgnoreRule]:
    """Generate an IgnoreRule object from given pattern.

    Take a .gitignore match pattern, such as "*.py[cod]" or "**/*.bak",
    and return an IgnoreRule suitable for matching against files and
    directories. Patterns which do not match files, such as comments
    and blank lines, will return None.
    Because git allows for nested .gitignore files, a base_path value
    is required for correct behavior. The base path should be absolute.
    """
    if base_path and not Path(base_path).anchor:
        raise ValueError("base_path must be absolute")
    base_path = str(base_path).replace(os.sep, "/")

    # A blank line matches no files, so it can serve as a separator for
    # readability.
    # A line starting with `#` serves as a comment. Put a backslash (\) in
    # front of the first hash for patterns that begin with a hash.
    if not pattern or pattern.startswith("#"):
        return None

    negation = pattern.startswith("!")

    pending_spaces = None

    # so parts[-1] always works
    parts = [""]

    # used to determine if the pattern is anchored
    first_separator_index = None
    index = 0
    for index, match in enumerate(GITIGNORE_PATTERN.finditer(pattern, pos=negation), start=1):
        # Trailing spaces are ignored unless they are quoted with backslash (\)
        # buffer spacing until next loop (aka it's not trailing). Escaped
        # spaces handled in escaped_char section
        if pending_spaces:
            pending_spaces = parts.append(pending_spaces)

        # only one of these groups won't be an empty string
        (
            separator,
            star_star,
            star,
            question_mark,
            bracket_expression,
            escaped_char,
            name_piece,
            spaces,
            _,
        ) = match.groups()

        if separator:
            # used to determine if the pattern is anchored
            first_separator_index = first_separator_index or index
            # handle `a/**/b` matching `a/b`
            if parts[-1] == STAR_STAR_REGEX:
                # `!foo/**/` *needs* to match things with a trailing slash
                parts[-1] = ".*/" if negation else "(?:.*/)?"
            else:
                parts.append("/")

        elif star_star:
            parts.append(STAR_STAR_REGEX)
        elif star:
            parts.append(STAR_REGEX)
        elif question_mark:
            parts.append(QUESTION_MARK_REGEX)
        elif bracket_expression:
            parts.append(_translate_brackets(bracket_expression))
        elif escaped_char:
            parts.append(re.escape(escaped_char[1]))
        elif name_piece:
            parts.append(re.escape(name_piece))

        elif spaces:
            # Trailing spaces are ignored unless they are quoted with
            # backslash, which is handled by the escaped_char section
            pending_spaces = spaces
            # Index used to check if last element was `/`.
            # Pending spaces don't count.
            index -= 1
            continue
        else:
            logging.error("error from %s on line %s\n%s", source[0], source[1], pattern)
            return None

    # remove '' from start of list
    parts = parts[1:]

    # if was whitespace or just a slash
    if not parts or parts == ["/"]:
        return None

    # special pattern under git?
    if parts == [STAR_REGEX, "/"] and negation:
        return None

    anchored = first_separator_index not in (None, index)
    directory_only = parts[-1] == "/"
    dir_only_ending = ""

    # Also match potential folder contents
    if parts[-1] == STAR_REGEX:
        parts.append("(?:/.*)?")
    elif directory_only:
        # used after verifying path is dir
        dir_only_ending = "(?:/.*)?"
        # assume paths that don't end in slash are files
        parts[-1] = "/.*"
    else:
        parts.append("(?:/.*)?")

    regex, dir_only_regex = _build_regex(base_path, parts, dir_only_ending, anchored)

    return IgnoreRule(
        pattern=pattern,
        regex=regex,
        dir_only_regex=dir_only_regex,
        negation=negation,
        directory_only=directory_only,
        source=source,
    )


ESCAPED_CHAR_OR_SLASH_PATTERN = re.compile(r"\\(.)|([\\/])")


def _translate_brackets(bracket_expression: str) -> str:
    bracket_regex = ESCAPED_CHAR_OR_SLASH_PATTERN.sub(_unescape, bracket_expression)
    # both ! and ^ are valid negation in .gitignore
    # but only ^ is interpreted as negation in regex.
    if bracket_regex.startswith("[!"):
        bracket_regex = "[^" + bracket_regex[2:]
    return bracket_regex


def _unescape(match: re.Match) -> str:
    escaped_char = match.group(1)

    # don't allow path separators in brackets
    if match.group(2) or escaped_char in r"\/":
        return ""

    # only keep escaping if \- or \^
    # Otherwise \0 and \d would be wrong
    if match.group(1) in "-^":
        return match.group(0)
    return match.group(1)


def _build_regex(base_path: str, parts: list[str], dir_only_ending: str, anchored: bool) -> tuple[str, str]:
    # leading slash handled by anchor
    if base_path.endswith("/"):
        base_path = base_path[:-1]

    anchor = "/" if anchored else "/(?:.*/)?"

    # leading slash handled by anchor
    if parts[0].startswith("/"):
        parts[0] = parts[0][1:]

    partial_regex = re.escape(base_path) + anchor + "".join(parts[:-1])
    regex = partial_regex + parts[-1]

    if dir_only_ending:
        return regex, partial_regex + dir_only_ending

    return regex, regex
