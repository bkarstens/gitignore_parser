from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Generator, Tuple, List, Union
from unittest import TestCase
from unittest.mock import mock_open, patch
from git.repo import Repo

from gitignore_parser import parse_gitignore, parse_gitignore_lines


@contextmanager
def TemporaryRepo(gitignore_content) -> Generator[Tuple[Repo, Path], None, None]:
    with TemporaryDirectory() as base_dir, Repo.init(base_dir) as repo:
        base_dir = Path(base_dir)
        gitignore_path = base_dir / ".gitignore"
        with gitignore_path.open("wt", encoding="utf-8") as gitignore:
            gitignore.write(gitignore_content)
        yield repo, gitignore_path


class Test(TestCase):
    def _test_matches_git(self, gitignore_content: Union[str, List[str]], paths: List[str]):
        if isinstance(gitignore_content, list):
            gitignore_content = "\n".join(gitignore_content)
        with TemporaryRepo(gitignore_content) as (repo, gitignore_path):
            ignored = parse_gitignore(gitignore_path)
            paths = [str(gitignore_path.parent / path) for path in paths]
            ignored_by_git = {*repo.ignored(paths)}
            ignored_by_parser = {*ignored(paths)}
            self.assertSetEqual(ignored_by_parser, ignored_by_git)

    def test_simple(self):
        ignore_lines = "__pycache__/\n*.py[cod]"
        paths = ["main.py", "main.pyc", "dir/main.pyc", "__pycache__/"]
        self._test_matches_git(ignore_lines, paths)

    def test_simple_lines(self):
        matches = parse_gitignore_lines(["__pycache__/\n", "*.py[cod]"], base_dir="/home/michael")
        self.assertFalse(matches("/home/michael/main.py"))
        self.assertTrue(matches("/home/michael/main.pyc"))
        self.assertTrue(matches("/home/michael/dir/main.pyc"))
        self.assertTrue(matches("/home/michael/__pycache__/"))

    def test_base_slash(self):
        matches = parse_gitignore_lines(["__pycache__/\n", "*.py[cod]"], base_dir="/home/michael/")
        self.assertFalse(matches("/home/michael/main.py"))
        self.assertTrue(matches("/home/michael/main.pyc"))
        self.assertTrue(matches("/home/michael/dir/main.pyc"))
        self.assertTrue(matches("/home/michael/__pycache__/"))

    def test_generator(self):
        matches = parse_gitignore_lines(["__pycache__/\n", "*.py[cod]"], base_dir="/home/michael")

        paths = [
            "/home/michael/main.py",
            "/home/michael/main.pyc",
            "/home/michael/dir/main.pyc",
            "/home/michael/__pycache__/",
        ]
        expected_output = [
            "/home/michael/main.pyc",
            "/home/michael/dir/main.pyc",
            "/home/michael/__pycache__/",
        ]
        for path, expected in zip(matches.match_iter(paths), expected_output):
            self.assertEqual(path, expected)

    def test_empty(self):
        lines = []
        paths = ["main.py", "main.pyc", "dir/main.pyc", "__pycache__/"]
        self._test_matches_git(lines, paths)

    def test_simple_many(self):
        lines = "__pycache__/\n*.py[cod]"
        paths = ["main.py", "main.pyc", "dir/main.pyc", "__pycache__/"]
        self._test_matches_git(lines, paths)

    def test_wildcard(self):
        lines = "hello.*"
        paths = [
            "hello.txt",
            "hello.foobar/",
            "dir/hello.txt",
            "hello.",
            "hello",
            "helloX",
        ]
        self._test_matches_git(lines, paths)

    def test_question_mark(self):
        lines = "file.???"
        paths = [
            "file",
            "file.c",
            "file.md",
            "file.txt",
            "file.log",
            "file.log/foobar",
        ]
        self._test_matches_git(lines, paths)

    def test_errors(self):
        lines = "foo/***/bar\nfoo[].txt"
        paths = [
            "foo/bar",
            "foo/fiz/bar",
            "foo/fiz/buz/bar",
            "foo.txt",
            "foo[].txt",
            "foo0.txt",
            "foobar",
        ]
        self._test_matches_git(lines, paths)

    def test_anchored_wildcard(self):
        lines = "/hello.*"
        paths = ["hello.txt", "hello.c", "a/hello.java"]
        self._test_matches_git(lines, paths)

    def test_trailingspaces(self):
        lines = (
            "ignoretrailingspace \n"
            "notignoredspace\\ \n"
            "partiallyignoredspace\\  \n"
            "partiallyignoredspace2 \\  \n"
            "notignoredmultiplespace\\ \\ \\ "
        )
        paths = [
            "ignoretrailingspace",
            "ignoretrailingspace ",
            "partiallyignoredspace ",
            "partiallyignoredspace  ",
            "partiallyignoredspace",
            "partiallyignoredspace2  ",
            "partiallyignoredspace2   ",
            "partiallyignoredspace2 ",
            "partiallyignoredspace2",
            "notignoredspace ",
            "notignoredspace",
            "notignoredmultiplespace   ",
            "notignoredmultiplespace",
        ]
        self._test_matches_git(lines, paths)

    def test_comment(self):
        lines = "somematch\n" "#realcomment\n" "othermatch\n" "\\#imnocomment"
        paths = [
            "somematch",
            "#realcomment",
            "othermatch",
            "#imnocomment",
        ]
        self._test_matches_git(lines, paths)

    def test_ignore_directory(self):
        lines = ".venv/"
        # git assumes things are files if they don't exist
        paths = [
            ".venv",
            ".venv/",
            ".venv/folder",
            ".venv/file.txt",
        ]
        self._test_matches_git(lines, paths)

    def test_ignore_directory_asterisk(self):
        lines = ".venv/*"
        paths = [
            ".venv",
            ".venv/",
            ".venv/folder",
            ".venv/file.txt",
        ]
        self._test_matches_git(lines, paths)

    def test_negation(self):
        lines = "*.ignore\n!keep.ignore"
        paths = [
            "trash.ignore",
            "keep.ignore",
            "waste.ignore",
        ]
        self._test_matches_git(lines, paths)

    def test_double_asterisks(self):
        lines = "foo/**/Bar"
        paths = [
            "foo/hello/Bar",
            "foo/world/Bar",
            "foo/Bar",
        ]
        self._test_matches_git(lines, paths)

    def test_extra_separators(self):
        lines = "foo//Bar"
        paths = [
            "foo//hello/Bar",
            "foo///////world/Bar",
            "foo//Bar",
        ]
        self._test_matches_git(lines, paths)

    def test_more_asterisks_handled_like_single_asterisk(self):
        """Test that multiple asterisk in a row are treated as a single asterisk."""

        lines = "***a/b\n"
        paths = [
            "XYZa/b",
            "foo/a/b",
        ]
        self._test_matches_git(lines, paths)

    def test_directory_only_negation(self):
        lines = """
data/**
!data/**/
!.gitkeep
!data/01_raw/*
            """
        paths = [
            "data/01_raw/",
            "data/01_raw/.gitkeep",
            "data/01_raw/raw_file.csv",
            "data/02_processed/",
            "data/02_processed/.gitkeep",
            "data/02_processed/processed_file.csv",
        ]
        self._test_matches_git(lines, paths)

    def test_single_asterisk(self):
        lines = "*"
        paths = [
            "file.txt",
            "directory",
            "directory-trailing/",
        ]
        self._test_matches_git(lines, paths)

    def test_bracket_escapes(self):
        lines = r"foo[\0].txt\nfoo[1\-3\w].txt"
        paths = [
            "foo0.txt",
            r"foo\.txt",
            "foo1.txt",
            "foo2.txt",
            "foo3.txt",
            "foo-.txt",
            "foow.txt",
            "fooq.txt",
        ]
        self._test_matches_git(lines, paths)

    def test_negated_bracket(self):
        lines = r"foo[^1-3].txt"
        paths = [
            "foo0.txt",
            "foo1.txt",
            "foo2.txt",
            "foo3.txt",
            "foo4.txt",
            "foop.txt",
        ]
        self._test_matches_git(lines, paths)

        lines = r"foo[!1-3].txt"
        paths = [
            "foo0.txt",
            "foo1.txt",
            "foo2.txt",
            "foo3.txt",
            "foo4.txt",
            "foop.txt",
        ]
        self._test_matches_git(lines, paths)

    def test_slash_in_range_does_not_match_dirs(self):
        """Tests that a slash in a range does not match directories."""
        lines = r"abc[X-Z/]def"
        paths = [
            "abcdef",
            "abcXdef",
            "abcYdef",
            "abcZdef",
            "abc/def",
            "abcXYZdef",
        ]
        self._test_matches_git(lines, paths)

    def test_double_asterisk_without_slashes_handled_like_single_asterisk(self):
        """Test that a double asterisk without slashes is treated like a single asterisk."""
        lines = r"a/b**c/d"
        paths = [
            "a/bc/d",
            "a/bXc/d",
            "a/bbc/d",
            "a/bcc/d",
            "a/bcd",
            "a/b/c/d",
            "a/bb/cc/d",
            "a/bb/XX/cc/d",
        ]
        self._test_matches_git(lines, paths)

    def test_part_of_name(self):
        lines = "build/"
        paths = [
            "folder1/folder2/extra_build/folder3/file.txt",
            "folder1/folder2/extra_build.txt",
            "folder1/build.txt",
            "extra_build.txt",
            "build.txt",
            "build",
            "build/",
            "folder1/build/",
            "folder1/build/folder2",
            "folder1/build/file.txt",
            "folder1/build/folder2/file.txt",
        ]
        self._test_matches_git(lines, paths)

    def test_trailing_slash(self):
        lines = "build/    "
        paths = [
            "folder1/folder2/extra_build/folder3/file.txt",
            "folder1/folder2/extra_build.txt",
            "folder1/build.txt",
            "extra_build.txt",
            "build.txt",
            "build",
            "build/",
        ]
        self._test_matches_git(lines, paths)

    def test_asterisk_folder(self):
        lines = "foo*"
        paths = [
            "foo.txt",
            "foo/bar.txt",
            "fiz/foo.txt",
            "fiz/bar.txt",
            "fiz/foo/bar.txt",
            "fiz/foo/bar/buz.txt",
        ]
        self._test_matches_git(lines, paths)

    def test_negation_complex(self):
        self.skipTest('borked')
        lines = """
/foo/**/bar*
!/foo/bar
!barfiz/
foo/barfiz/buz
!fiz
        """

        paths = [  # git ignores this path even though `!fiz`?
            "foo/fiz/bar",
            "foo/bar/fiz",
            # git ignores this path even though `!fiz`?
            "foo/barfoo/fiz",
            "foo/barfoo.txt",
            "foo/barfiz/asdf.txt",
            # git ignores this path even though `!fiz`?
            "foo/fiz/barfiz/asdf.txt",
            # git ignores this path even though `!fiz`?
            "foo/fiz/barfiz/buz/asdf.txt",
            "foo/barfiz/buz",
            "foo/bar",
            "foo/bar.txt",
            # git ignores this path even though `!fiz`?
            "foo/barfiz/buz/fiz",
            "fiz/foo/barfiz/buz",
            "asdf/foo/barfiz/buz",
        ]
        self._test_matches_git(lines, paths)

    def test_negation_simple(self):
        self.skipTest('borked')
        # https://git-scm.com/docs/gitignore:
        # An optional prefix "!" which negates the pattern; any matching file excluded by a previous pattern will become
        # included again. It is not possible to re-include a file if a parent directory of that file is excluded. Git
        # doesn’t list excluded directories for performance reasons, so any patterns on contained files have no effect,
        # no matter where they are defined. Put a backslash ("\") in front of the first "!" for patterns that begin with
        # a literal "!", for example, "\!important!.txt".
        # ======
        # I'm not wrong, Git's wrong. "any matching file excluded by a previous pattern will become included again."
        # or maybe I am wrong. !b matches a folder? By the time it gets to the second line, the obj being matched is the
        # file /a/b/c, then !b doesn't match /a/b/c because.. it's not b? whereas !b/c
        lines = ["/a/**/c", "!b"]
        paths = ["a/b/c"]
        self._test_matches_git(lines, paths)

    def test_directory_only(self):
        matches = _parse_gitignore_string("foo/", fake_base_dir="/home/michael", honor_directory_only=True)
        with patch("os.path.isdir", lambda path: True):
            self.assertTrue(matches("/home/michael/foo"))
        with patch("os.path.isdir", lambda path: False):
            self.assertFalse(matches("/home/michael/foo"))
            self.assertTrue(matches("/home/michael/foo/bar.txt"))

    def test_negated_directory_only(self):
        matches = _parse_gitignore_string("**\n!foo/", fake_base_dir="/home/michael", honor_directory_only=True)
        with patch("os.path.isdir", lambda path: True):
            self.assertFalse(matches("/home/michael/foo"))
            self.assertFalse(matches("/home/michael/foo/"))
        with patch("os.path.isdir", lambda path: False):
            self.assertTrue(matches("/home/michael/foo"))
            self.assertFalse(matches("/home/michael/foo/bar.txt"))

    def test_supports_path_type_argument(self):
        matches = _parse_gitignore_string("file1\n!file2", fake_base_dir="/home/michael")
        self.assertTrue(matches(Path("/home/michael/file1")))
        self.assertFalse(matches(Path("/home/michael/file2")))

    def test_simple_asdf(self):
        # self.skipTest('borked')
        lines = [
            "*",  # Ignore all files by default
            "!*/",  # but scan all directories
            "!*.txt",  # Text files
            "/test1/**",  # ignore all in the directory
        ]
        paths = [
            "test1/b.bin",
            "test1/a.txt",
            "test1/c/c.txt",
            "test2/a.txt",
            "test2/b.bin",
            "test2/c/c.txt",
        ]
        self._test_matches_git(lines, paths)


def _parse_gitignore_string(data: str, fake_base_dir: str = None, honor_directory_only: bool = False):
    with patch("builtins.open", mock_open(read_data=data)):
        success = parse_gitignore(f"{fake_base_dir}/.gitignore", fake_base_dir, honor_directory_only)
        return success


if __name__ == "__main__":
    import unittest

    unittest.main()
