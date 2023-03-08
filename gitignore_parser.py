"""Gitignore parser for Python."""
import logging
import os.path
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generator, Iterable, List, Tuple, Union, overload

__all__ = [
    'IgnoreRule',
    'GitignoreMatcher',
    'parse_gitignore',
    'parse_gitignore_lines',
    'rule_from_pattern']

# %%
GITIGNORE_PATTERN = re.compile(
    # a forward slash
    r'(?P<separator>\/)|'

    # two asterisks not preceded or followed by an asterisk
    r'(?P<star_star>(?<!\*)\*\*(?!\*))|'

    # one asterisk not preceded or followed by an asterisk
    r'(?P<star>(?<!\*)\*(?!\*))|'

    # a question mark
    r'(?P<question_mark>\?)|'

    # square brackets around characters
    r'(?P<bracket_expression>\[(?:\\.|[^\\])+\])|'

    # backslash followed by any char. Assuming escaped char.
    r'(?P<escaped_char>\\.)|'

    # not a space, slash, asterisk, question mark, opening or closing square
    # brackets, newline, or backslash
    r'(?P<name_piece>[^ \/\*\?\[\]\n\\]+)|'

    # space characters
    r'(?P<spaces>\s+)|'

    # 3 or more asterisks
    r'(?P<error_stars>\*{3,})|'

    # something went wrong; catch all
    r'(?P<error>.+)',
    re.MULTILINE
)

# The character `?` matches any one character except `/`.
QUESTION_MARK_REGEX = '[^/]'
# An asterisk `*` matches anything except a slash.
STAR_REGEX = '[^/]*'
STAR_STAR_REGEX = '.*'

ESCAPED_CHAR_PATTERN = re.compile(r'\\(.)')

# %%


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    """Class representing a single rule parsed from a .ignore file."""

    pattern:            str  # the .gitignore pattern
    source: Tuple[str, int]  # (file, line), for reporting

    regex:              str  # the regex string of the rule
    dir_only_regex:     str  # the regex to use if the comparing path is a dir

    negation:          bool  # if the rule is a negation of previous rules
    directory_only:    bool  # if the pattern has special regex when dir

    def __str__(self):
        """Return string representation (user friendly) of the rule."""
        return self.pattern

# %%


class GitignoreMatcher:
    """Class representing all rules from a .ignore file."""

    def __init__(self,
                 rules: Iterable[IgnoreRule],
                 honor_directory_only: bool) -> None:
        """Create a GitignoreMatcher object from the given rules.

        Args:
            rules (Iterable[IgnoreRule]): Iterable of rules
            honor_directory_only (bool): False assumes paths not ending with a
            slash are not dirs. True verifies if they are dirs
        """
        self.rules = rules
        pattern = ''
        dir_only_pattern = ''
        dir_only_rules = False
        for rule in rules:
            dir_only_rules = dir_only_rules or rule.directory_only
            if rule.negation:
                if pattern:
                    pattern = f'(?!{rule.regex}$)(?:{pattern})'
                    dir_only_pattern = (
                        f'(?!{rule.dir_only_regex}$)'f'(?:{pattern})')
                # negation as the first rule(s) does nothing. no else here
            elif pattern:
                pattern = f'{pattern}|{rule.regex}'
                dir_only_pattern = f'{dir_only_pattern}|{rule.dir_only_regex}'
            else:
                pattern = rule.regex
                dir_only_pattern = rule.dir_only_regex

        self.regex = re.compile(pattern)
        self.honor_directory_only = honor_directory_only and dir_only_rules
        if self.honor_directory_only:
            self.dir_only_regex = re.compile(dir_only_pattern)

    def _call(self, path: Union[str, Path]) -> bool:
        """Check if given path should be ignored.

        Args:
            path (str | Path): The path to check.

        Returns:
            bool: True if path should be ignored, else False.
        """
        if isinstance(path, Path):
            path = path.as_posix()
        if self.honor_directory_only and os.path.isdir(path):
            return self.dir_only_regex.fullmatch(path) is not None
        return self.regex.fullmatch(path) is not None

    @overload
    def __call__(self, path: Union[str, Path]) -> bool:
        """Check if given path should be ignored.

        Args:
            path (str | Path): The path to check.

        Returns:
            bool: True if path should be ignored, else False.
        """

    @overload
    def __call__(self,
                 paths: Iterable[Union[str, Path]]) -> List[Union[str, Path]]:
        """Check if the given paths should be ignored.

        Args:
            paths (Iterable[str | Path]): the paths to be checked.

        Returns:
            list[str | Path]: a list of the ignored paths.
        """

    def __call__(self,
                 path_or_paths: Union[str, Path, Iterable[Union[str, Path]]]
                 ) -> Union[bool, List[Union[str, Path]]]:
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

    def match_iter(self,
                   paths: Iterable[Union[str, Path]]
                   ) -> Generator[Union[str, Path], None, None]:
        """Check if the given paths should be ignored [Generator].

        Args:
            paths (Iterable[str | Path]): The paths to be checked.

        Yields:
            Generator[str | Path, None, None]: Each matching path.
        """
        for path in paths:
            if self._call(path):
                yield path

    def __repr__(self) -> str:
        """Return string representation (developer friendly) of the rules."""
        return f'GitignoreMatcher(rules={self.rules!r})'


# %%


def parse_gitignore(gitignore_path: Union[str, Path],
                    base_dir: str,
                    honor_directory_only: bool = False
                    ) -> Callable[[Union[str, Path]], bool]:
    """Parse a gitignore file."""
    with open(gitignore_path, encoding='utf-8') as gitignore_file:
        gitignore_content = gitignore_file.read()
    return parse_gitignore_lines(gitignore_content.splitlines(), base_dir,
                                 str(gitignore_path), honor_directory_only)


def parse_gitignore_lines(gitignore_lines: List[str],
                          base_dir: str, source: str = '',
                          honor_directory_only: bool = False
                          ) -> Callable[[Union[str, Path]], bool]:
    """Parse a list of lines matching gitignore syntax."""
    generator = _rule_generator(gitignore_lines, base_dir, source)

    return GitignoreMatcher(generator, honor_directory_only)


def _rule_generator(gitignore_lines: List[str],
                    base_dir: str, source: str
                    ) -> Generator[IgnoreRule, None, None]:
    for line_number, line in enumerate(gitignore_lines, start=1):
        ignore_rule = rule_from_pattern(
            pattern=line, base_path=base_dir, source=(source, line_number))
        if ignore_rule:
            yield ignore_rule


def rule_from_pattern(pattern,
                      base_path,
                      source: Tuple[str, int] = ('Unknown', 0)
                      ) -> Union[IgnoreRule, None]:
    """Generate an IgnoreRule object from given pattern.

    Take a .gitignore match pattern, such as "*.py[cod]" or "**/*.bak",
    and return an IgnoreRule suitable for matching against files and
    directories. Patterns which do not match files, such as comments
    and blank lines, will return None.
    Because git allows for nested .gitignore files, a base_path value
    is required for correct behavior. The base path should be absolute.
    """
    # A blank line matches no files, so it can serve as a separator for
    # readability.
    # A line starting with `#` serves as a comment. Put a backslash (\) in
    # front of the first hash for patterns that begin with a hash.
    if not pattern or pattern.startswith('#'):
        return

    negation = pattern.startswith('!')

    pending_spaces = ''

    parts = ['']

    first_separator_index = 0
    index = 0
    for index, match in enumerate(
            GITIGNORE_PATTERN.finditer(pattern, pos=negation), start=1):
        # Trailing spaces are ignored unless they are quoted with backslash (\)
        # buffer spacing until next loop (aka it's not trailing). Escaped
        # spaces handled in escaped_char section
        if pending_spaces:
            parts.append(pending_spaces)
            pending_spaces = ''

        # only one of these groups won't be an empty string
        (separator,
         star_star,
         star,
         question_mark,
         bracket_expression,
         escaped_char,
         name_piece,
         spaces,
         error_stars,
         _) = match.groups()

        if separator:
            # used to determine if the pattern is anchored
            first_separator_index = first_separator_index or index
            # handle `a/**/b` matching `a/b`
            if parts[-1] == STAR_STAR_REGEX:
                # `!foo/**/` *needs* to match things with a trailing slash,
                is_optional = '' if negation else '?'
                parts[-1] = '(?:.*/)' + is_optional
            else:
                parts.append('/')

        elif star_star:
            parts.append(STAR_STAR_REGEX)
        elif star:
            parts.append(STAR_REGEX)
        elif question_mark:
            parts.append(QUESTION_MARK_REGEX)

        elif bracket_expression:
            def sub(match: re.Match) -> str:
                if match.group(1) in r'\-^':
                    return match.group(0)
                return match.group(1)
            # only keep escaping if \\, \-, or \^
            # Otherwise \0 and \d would be wrong
            bracket_regex = ESCAPED_CHAR_PATTERN.sub(sub, bracket_expression)
            # both ! and ^ are valid negation in .gitignore (from testing)
            # but only ^ is interpreted as negation in regex.
            if bracket_regex.startswith('[!'):
                bracket_regex = '[^' + bracket_regex[2:]
            parts.append(bracket_regex)

        elif escaped_char:
            parts.append(re.escape(escaped_char[1]))

        elif name_piece:
            parts.append(re.escape(name_piece))

        elif spaces:
            # Trailing spaces are ignored unless they are quoted with
            # backslash, which is handled by the escaped_char section
            pending_spaces = spaces
            index -= 1
            continue
        elif error_stars:
            logging.error(
                'error from %s on line %s\n%s\n%s%s', source[0], source[1],
                pattern, " " * match.start(), "^" * len(match.group(0)))
            return
        else:
            logging.error(
                'error from %s on line %s\n%s', source[0], source[1],
                pattern)
            return
    parts = parts[1:]
    dir_only_ending = None
    # if was whitespace or just a slash
    if not parts or parts == ['/']:
        return

    anchored = first_separator_index and first_separator_index != index
    directory_only = parts[-1] == '/'

    # Also match potential folder contents
    if parts[-1] == STAR_REGEX:
        parts.append('(?:/.*)?')
    elif directory_only:
        # used after verifying path is dir
        dir_only_ending = '(?:/.*)?'
        # assume paths that don't end in slash are files
        parts[-1] = '/.*'
    else:
        parts.append('(?:/.*)?')

    regex, dir_only_regex = _build_regex(
        base_path, parts, dir_only_ending, anchored)

    return IgnoreRule(
        pattern=pattern,
        regex=regex,
        dir_only_regex=dir_only_regex,
        negation=negation,
        directory_only=directory_only,
        source=source)


def _build_regex(base_path: str,
                 parts: List[str],
                 dir_only_ending: Union[str, None],
                 anchored: bool
                 ) -> Tuple[str, str]:

    # leading slash handled by anchor
    if base_path.endswith('/'):
        base_path = base_path[:-1]

    anchor = '/' if anchored else '/(?:.*/)?'

    # leading slash handled by anchor
    if parts[0].startswith('/'):
        parts[0] = parts[0][1:]

    partial_regex = re.escape(base_path) + anchor + ''.join(parts[:-1])
    regex = partial_regex + parts[-1]

    if dir_only_ending:
        return regex, partial_regex + dir_only_ending
    else:
        return regex, regex
