# %%
import re
from typing import Callable, Union, List, Tuple
from pathlib import Path
import os.path
import collections
import logging

# %%
GITIGNORE_PATTERN = re.compile(
    r'(?P<separator>\/)|'  # a forward slash
    r'(?P<star_star>(?<!\*)\*\*(?!\*))|'  # two asterisks not preceded or followed by an asterisk
    r'(?P<star>(?<!\*)\*(?!\*))|'  # one asterisk not preceded or followed by an asterisk
    r'(?P<question_mark>\?)|'  # a question mark
    r'(?P<bracket_expression>\[(?:\\.|[^\\])+\])|'  # square brackets around characters
    r'(?P<escaped_char>\\.)|'  # backslash followed by any char. Assuming escaped char.
    r'(?P<name_piece>[^ \/\*\?\[\]\n\\]+)|'  # not a space, slash, asterisk, question mark, opening or closing square brackets, newline, or backslash
    r'(?P<spaces>\s+)|'  # space characters
    r'(?P<error_stars>\*{3,})|'  # 3 or more asterisks
    r'(?P<error>.+)',  # something went wrong; catch all
    re.MULTILINE
)

ESCAPED_CHAR_PATTERN = re.compile(r'\\(.)')

# %%
IGNORE_RULE_FIELDS = [
    'pattern', 'regex', 'dir_only_regex',  # Basic values
    'negation', 'directory_only', 'anchored',  # Behavior flags
    'base_path',  # Meaningful for gitignore-style behavior
    'source'  # (file, line) tuple for reporting
]


class IgnoreRule(collections.namedtuple('IgnoreRule_', IGNORE_RULE_FIELDS)):
    def __str__(self):
        return self.pattern

    def __repr__(self):
        return f"IgnoreRule('{self.pattern}')"

    # def __init__(self, *args, **kwargs):
        # self.match = self.regex.fullmatch

# %%


class GitignoreMatch:
    def __init__(self, rules: List[IgnoreRule], honor_directory_only: bool) -> None:
        self.rules = rules
        pattern = ''
        pattern_dir_only = ''
        self.honor_directory_only = honor_directory_only
        for rule in rules:
            if rule.negation:
                if pattern:  # trim trailing ? for folder only negation
                    pattern = f'(?!{rule.regex}$)(?:{pattern})'
                    pattern_dir_only = f'(?!{rule.dir_only_regex}$)(?:{pattern})'
            else:
                if pattern:
                    pattern = f'{pattern}|{rule.regex}'
                    pattern_dir_only = f'{pattern_dir_only}|{rule.dir_only_regex}'
                else:
                    pattern = rule.regex
                    pattern_dir_only = rule.dir_only_regex
        self.regex = re.compile(pattern)
        self.dir_only_regex = re.compile(pattern_dir_only)

    def __call__(self, path) -> bool:
        if isinstance(path, Path):
            path = path.as_posix()
        if not self.honor_directory_only or os.path.isdir(path):
            return self.dir_only_regex.fullmatch(path) is not None
        return self.regex.fullmatch(path) is not None

    def __repr__(self):
        return f'GitignoreMatch(rules={self.rules!r})'



# %%


def parse_gitignore(gitignore_path: Union[str, Path], base_dir: str, honor_directory_only: bool = False) -> Callable[[str], bool]:

    with open(gitignore_path) as gitignore_file:
        gitignore_content = gitignore_file.read()
    return parse_gitignore_lines(gitignore_content.splitlines(), base_dir, str(gitignore_path), honor_directory_only)


def parse_gitignore_lines(gitignore_lines: List[str], base_dir: str, source='', honor_directory_only: bool = False) -> Callable[[str], bool]:

    rules = []
    for line_number, line in enumerate(gitignore_lines):
        ignore_rule = rule_from_pattern(pattern=line, base_path=base_dir, source=(source, line_number))
        if ignore_rule:
            rules.append(ignore_rule)

    return GitignoreMatch(rules, honor_directory_only)


def rule_from_pattern(pattern, base_path, source: Tuple[str, int] = ('Unknown', 0)):
    """
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

    regex_translation = ['']  # should match if path is a file
    dir_only_regex_translation = ['']  # should match if path is a dir

    def append_translation(regex, dir_only_regex=None):
        regex_translation.append(regex)
        dir_only_regex_translation.append(dir_only_regex or regex)

    first_separator_index = 0
    index = 0
    for index, match in enumerate(GITIGNORE_PATTERN.finditer(pattern, pos=negation), start=1):
        # Trailing spaces are ignored unless they are quoted with backslash (\).
        # buffer spacing until next loop (aka it's not trailing). Escaped spaces
        # handled in escaped_char section
        if pending_spaces:
            append_translation(pending_spaces)
            pending_spaces = ''

        # only one of these groups won't be an empty string
        separator, star_star, star, question_mark, bracket_expression, \
            escaped_char, name_piece, spaces, error_stars, error = match.groups()

        if separator:
            first_separator_index = first_separator_index or index
            # handle `a/**/b` matching `a/b`
            if regex_translation[-1] == '.*':
                regex_translation[-1] = '(?:.*/)?'
                dir_only_regex_translation[-1] = '(?:.*/)?'
            else:
                append_translation('/')

        elif star_star:
            append_translation('.*')

        elif star:
            # An asterisk `*` matches anything except a slash.
            append_translation('[^/]*')

        elif question_mark:
            # The character `?` matches any one character except `/`.
            append_translation('[^/]')

        elif bracket_expression:
            def sub(match: re.Match) -> str:
                if match.group(1) in r'\-^':
                    return match.group(0)
                return match.group(1)
            # only keep escaping if \\,\-,\^. otherwise \0 and \d would be wrong
            bracket_regex = ESCAPED_CHAR_PATTERN.sub(sub, bracket_expression)
            # both ! and ^ are valid negation in .gitignore but only ^ is interpreted as negation in regex.
            if bracket_regex.startswith('[!'):
                bracket_regex = '[^' + bracket_regex[2:]
            append_translation(bracket_regex)

        elif escaped_char:
            append_translation(re.escape(escaped_char[1]))

        elif name_piece:
            append_translation(re.escape(name_piece))

        elif spaces:
            # Trailing spaces are ignored unless they are quoted with backslash (\).
            pending_spaces = spaces
            index -= 1
            continue
        elif error_stars:
            logging.error(f'error from {source[0]} on line {source[1]}\n{pattern}\n{" " * match.start()}{"^" * len(match.group(0))}')
            return
        else:
            logging.error(pattern)
            return
    else:
        regex_translation = regex_translation[1:]
        dir_only_regex_translation = dir_only_regex_translation[1:]
        # if was whitespace or just a slash
        if not regex_translation or regex_translation == ['/']:
            return
        anchored = first_separator_index and first_separator_index != index
        # Also match potential folder contents
        if regex_translation[-1] == '[^/]*':
            append_translation('(?:/.*)?')
        directory_only = regex_translation[-1] == '/'
        if directory_only:
            # keep content to compare against directory_only flag
            regex_translation[-1] = '/.*'
            dir_only_regex_translation[-1] = '(?:/.*)?'

        regex = (re.escape(base_path + '/' if not base_path.endswith('/') and not regex_translation[0].startswith('/') else base_path) +
                 ('' if anchored else '(?:.*/)?') +
                 ''.join(regex_translation))
        dir_only_regex = (re.escape(base_path + '/' if not base_path.endswith('/') and not regex_translation[0].startswith('/') else base_path) +
                          ('' if anchored else '(?:.*/)?') +
                          ''.join(dir_only_regex_translation))
        return IgnoreRule(
            pattern=pattern,
            regex=regex,
            dir_only_regex=dir_only_regex,
            negation=negation,
            directory_only=directory_only,
            anchored=anchored,
            base_path=base_path,
            source=source)
