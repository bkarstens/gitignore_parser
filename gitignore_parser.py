# %%
import re
from typing import Callable
from pathlib import PosixPath, WindowsPath, Path
import os.path
import collections
# %%
GITIGNORE_PATTERN = re.compile(
    r'(?P<separator>\/)|'  # a forward slash
    r'(?P<star_star>(?<!\*)\*\*(?!\*))|'  # two asterisks not preceded or followed by an asterisk
    r'(?P<star>(?<!\*)\*(?!\*))|'  # one asterisk not preceded or followed by an asterisk
    r'(?P<question_mark>\?)|'  # a question mark
    r'(?P<bracket_expression>\[(?:\\.|.)*\])|'  # square brackets around characters
    r'(?P<escaped_char>\\.)|'  # backslash followed by any char. Assuming escaped char.
    r'(?P<name_piece>[^ \/\*\?\[\]\n\\]+)|'  # not a space, slash, asterisk, question mark, opening or closing square brackets, newline, or backslash
    r'(?P<spaces>\s+)|'  # space characters
    r'(?P<error_stars>\*{3,})|'  # 3 or more asterisks
    r'(?P<error>.+)',  # something went wrong; catch all
    re.MULTILINE
)


class GitignoreMatch:
    def __init__(self, rules) -> None:
        self.rules = rules

    def __call__(self, path) -> bool:
        # Unix paths are allowed to have backslashes as parts of file and folder names
        if isinstance(path, PosixPath):
            path = str(path)
        elif isinstance(path, WindowsPath):
            path = str(path).replace('\\', '/')
        matched = False
        for rule in self.rules:
            if match := rule.match(path):
                # if we don't care if it's a folder, if it's a file in a folder to ignore,
                # if the path doesn't exist (assume it's not a file), or it is a folder
                # to be ignored
                if not rule.directory_only or match.group(1) or not os.path.exists(path) or os.path.isdir(path):
                    matched = not rule.negation
        return matched
        # return any((rule.match(path) is not None) for rule in self.rules)

    def __repr__(self):
        return f'GitignoreMatch(rules={self.rules!r})'


class GitignoreMatchFast(GitignoreMatch):
    def __init__(self, rules) -> None:
        super().__init__(rules)
        self.regex = re.compile('|'.join(rule.regex.pattern for rule in self.rules))

    def __call__(self, path) -> bool:
        # Unix paths are allowed to have backslashes as parts of file and folder names
        if isinstance(path, PosixPath):
            path = str(path)
        elif isinstance(path, WindowsPath):
            path = str(path).replace('\\', '/')
        return self.regex.fullmatch(path) is not None

    def __repr__(self):
        return f'GitignoreMatchBasic(rules={self.rules!r}, regex={self.regex!r})'


IGNORE_RULE_FIELDS = [
    'pattern', 'regex',  # Basic values
    'negation', 'directory_only', 'anchored',  # Behavior flags
    'base_path',  # Meaningful for gitignore-style behavior
    'source'  # (file, line) tuple for reporting
]


class IgnoreRule(collections.namedtuple('IgnoreRule_', IGNORE_RULE_FIELDS)):
    def __str__(self):
        return self.pattern

    def __repr__(self):
        return f"IgnoreRule('{self.pattern}')"

    def match(self, abs_path: str | Path) -> re.Match | None:
        return self.regex.fullmatch(abs_path)

# %%


def parse_gitignore(gitignore_path: str | Path, base_dir: str) -> Callable[[str], bool]:

    with open(gitignore_path) as gitignore_file:
        gitignore_content = gitignore_file.read()
    return parse_gitignore_lines(gitignore_content.splitlines(), base_dir, gitignore_path)


def parse_gitignore_lines(gitignore_lines: list[str], base_dir: str, source=None) -> Callable[[str], bool]:

    rules = []

    for line_number, line in enumerate(gitignore_lines):
        if ignore_rule := rule_from_pattern(pattern=line, base_path=base_dir, source=(source, line_number)):
            rules.append(ignore_rule)

    if any(rule.negation for rule in rules) or os.path.exists(base_dir) and any(rule.directory_only for rule in rules):
        return GitignoreMatch(rules)
    return GitignoreMatchFast(rules)


def rule_from_pattern(pattern, base_path, source=None):
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

    regex_translation = ['']
    first_separator_index = 0
    index = 0
    for index, match in enumerate(GITIGNORE_PATTERN.finditer(pattern, pos=negation), start=1):
        # Trailing spaces are ignored unless they are quoted with backslash (\).
        # buffer spacing until next loop (aka it's not trailing). Escaped spaces
        # handled in escaped_char section
        if pending_spaces:
            regex_translation.append(pending_spaces)
            pending_spaces = ''

        if match.group('error_stars'):
            # print(f'Error on pattern {line_number}:')
            print(pattern)
            print(f'{" " * match.start()}{"^" * len(match.group(0))}')
            return

        elif match.group('error'):
            # print(f'Unkown error on pattern {line_number}:')
            print(pattern)
            return

        elif match.group('separator'):
            first_separator_index = first_separator_index or index
            # handle `a/**/b` matching `a/b`
            if regex_translation[-1] == '.*':
                regex_translation[-1] = '(?:.*/)?'
            else:
                regex_translation.append('/')

        elif match.group('star_star'):
            regex_translation.append('.*')

        elif match.group('star'):
            # An asterisk `*` matches anything except a slash.
            regex_translation.append('[^/]*')

        elif match.group('question_mark'):
            # The character `?` matches any one character except `/`.
            regex_translation.append('[^/]')

        elif bracket_expression := match.group('bracket_expression'):
            regex_translation.append(bracket_expression)

        elif escaped_char := match.group('escaped_char'):
            regex_translation.append(re.escape(escaped_char[1]))

        elif name_piece := match.group('name_piece'):
            regex_translation.append(re.escape(name_piece))

        elif spaces := match.group('spaces'):
            # Trailing spaces are ignored unless they are quoted with backslash (\).
            pending_spaces = spaces
            index -= 1
            continue
    else:
        regex_translation = regex_translation[1:]
        # if was whitespace or just a slash
        if not regex_translation or regex_translation == ['/']:
            return
        anchored = first_separator_index and first_separator_index != index
        # Also match potential folder contents
        if regex_translation[-1] == '[^/]*':
            regex_translation.append('(?:/.*)?')
        if directory_only := regex_translation[-1] == '/':
            # keep content to  compare against directory_only flag
            regex_translation[-1] = '(/.*)?'

        regular_expression = (re.escape(base_path + '/' if not base_path.endswith('/') and not regex_translation[0].startswith('/') else base_path) +
                              ('' if anchored else '(?:.*/)?') +
                              ''.join(regex_translation))
        # print(f"`{pattern}` -> `{regular_expression}`")
        return IgnoreRule(
            pattern=pattern,
            regex=re.compile(regular_expression),
            negation=negation,
            directory_only=directory_only,
            anchored=anchored,
            base_path=base_path,
            source=source)

# %%
