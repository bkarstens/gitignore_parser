from unittest.mock import patch, mock_open
from pathlib import Path

from gitignore_parser import parse_gitignore, parse_gitignore_lines

from unittest import TestCase


class Test(TestCase):
    def test_simple(self):
        matches = _parse_gitignore_string(
            '__pycache__/\n'
            '*.py[cod]',
            fake_base_dir='/home/michael'
        )
        self.assertFalse(matches('/home/michael/main.py'))
        self.assertTrue(matches('/home/michael/main.pyc'))
        self.assertTrue(matches('/home/michael/dir/main.pyc'))
        self.assertTrue(matches('/home/michael/__pycache__/'))

    def test_simple_lines(self):
        matches = parse_gitignore_lines(['__pycache__/\n', '*.py[cod]'],
                                        base_dir='/home/michael')
        self.assertFalse(matches('/home/michael/main.py'))
        self.assertTrue(matches('/home/michael/main.pyc'))
        self.assertTrue(matches('/home/michael/dir/main.pyc'))
        self.assertTrue(matches('/home/michael/__pycache__/'))

    def test_simple_many(self):
        matches = parse_gitignore_lines(['__pycache__/\n', '*.py[cod]'],
                                        base_dir='/home/michael')

        ignored = matches(['/home/michael/main.py',
                           '/home/michael/main.pyc',
                           '/home/michael/dir/main.pyc',
                           '/home/michael/__pycache__/'])
        self.assertNotIn('/home/michael/main.py', ignored)
        self.assertIn('/home/michael/main.pyc', ignored)
        self.assertIn('/home/michael/dir/main.pyc', ignored)
        self.assertIn('/home/michael/__pycache__/', ignored)
        self.assertListEqual(['/home/michael/main.pyc',
                              '/home/michael/dir/main.pyc',
                              '/home/michael/__pycache__/'], ignored)

    def test_wildcard(self):
        matches = _parse_gitignore_string(
            'hello.*',
            fake_base_dir='/home/michael'
        )
        self.assertTrue(matches('/home/michael/hello.txt'))
        self.assertTrue(matches('/home/michael/hello.foobar/'))
        self.assertTrue(matches('/home/michael/dir/hello.txt'))
        self.assertTrue(matches('/home/michael/hello.'))
        self.assertFalse(matches('/home/michael/hello'))
        self.assertFalse(matches('/home/michael/helloX'))

    def test_anchored_wildcard(self):
        matches = _parse_gitignore_string(
            '/hello.*',
            fake_base_dir='/home/michael'
        )
        self.assertTrue(matches('/home/michael/hello.txt'))
        self.assertTrue(matches('/home/michael/hello.c'))
        self.assertFalse(matches('/home/michael/a/hello.java'))

    def test_trailingspaces(self):
        matches = _parse_gitignore_string(
            'ignoretrailingspace \n'
            'notignoredspace\\ \n'
            'partiallyignoredspace\\  \n'
            'partiallyignoredspace2 \\  \n'
            'notignoredmultiplespace\\ \\ \\ ',
            fake_base_dir='/home/michael'
        )
        self.assertTrue(matches('/home/michael/ignoretrailingspace'))
        self.assertFalse(matches('/home/michael/ignoretrailingspace '))
        self.assertTrue(matches('/home/michael/partiallyignoredspace '))
        self.assertFalse(matches('/home/michael/partiallyignoredspace  '))
        self.assertFalse(matches('/home/michael/partiallyignoredspace'))
        self.assertTrue(matches('/home/michael/partiallyignoredspace2  '))
        self.assertFalse(matches('/home/michael/partiallyignoredspace2   '))
        self.assertFalse(matches('/home/michael/partiallyignoredspace2 '))
        self.assertFalse(matches('/home/michael/partiallyignoredspace2'))
        self.assertTrue(matches('/home/michael/notignoredspace '))
        self.assertFalse(matches('/home/michael/notignoredspace'))
        self.assertTrue(matches('/home/michael/notignoredmultiplespace   '))
        self.assertFalse(matches('/home/michael/notignoredmultiplespace'))

    def test_comment(self):
        matches = _parse_gitignore_string(
            'somematch\n'
            '#realcomment\n'
            'othermatch\n'
            '\\#imnocomment',
            fake_base_dir='/home/michael'
        )
        self.assertTrue(matches('/home/michael/somematch'))
        self.assertFalse(matches('/home/michael/#realcomment'))
        self.assertTrue(matches('/home/michael/othermatch'))
        self.assertTrue(matches('/home/michael/#imnocomment'))

    def test_ignore_directory(self):
        matches = _parse_gitignore_string(
            '.venv/', fake_base_dir='/home/michael')
        # git assumes things are files if they don't exist
        self.assertFalse(matches('/home/michael/.venv'))
        self.assertTrue(matches('/home/michael/.venv/'))
        self.assertTrue(matches('/home/michael/.venv/folder'))
        self.assertTrue(matches('/home/michael/.venv/file.txt'))

    def test_ignore_directory_asterisk(self):
        matches = _parse_gitignore_string(
            '.venv/*', fake_base_dir='/home/michael')
        self.assertFalse(matches('/home/michael/.venv'))
        self.assertTrue(matches('/home/michael/.venv/'))
        self.assertTrue(matches('/home/michael/.venv/folder'))
        self.assertTrue(matches('/home/michael/.venv/file.txt'))

    def test_negation(self):
        matches = _parse_gitignore_string(
            '''
*.ignore
!keep.ignore
            ''',
            fake_base_dir='/home/michael'
        )
        self.assertTrue(matches('/home/michael/trash.ignore'))
        self.assertFalse(matches('/home/michael/keep.ignore'))
        self.assertTrue(matches('/home/michael/waste.ignore'))

    def test_double_asterisks(self):
        matches = _parse_gitignore_string(
            'foo/**/Bar', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/foo/hello/Bar'))
        self.assertTrue(matches('/home/michael/foo/world/Bar'))
        self.assertTrue(matches('/home/michael/foo/Bar'))

    def test_directory_only_negation(self):
        matches = _parse_gitignore_string('''
data/**
!data/**/
!.gitkeep
!data/01_raw/*
            ''',
                                          fake_base_dir='/home/michael'
                                          )
        self.assertFalse(matches('/home/michael/data/01_raw/'))
        self.assertFalse(matches('/home/michael/data/01_raw/.gitkeep'))
        self.assertFalse(matches('/home/michael/data/01_raw/raw_file.csv'))
        self.assertFalse(matches('/home/michael/data/02_processed/'))
        self.assertFalse(matches('/home/michael/data/02_processed/.gitkeep'))
        self.assertTrue(
            matches('/home/michael/data/02_processed/processed_file.csv'))

    def test_single_asterisk(self):
        matches = _parse_gitignore_string('*', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/file.txt'))
        self.assertTrue(matches('/home/michael/directory'))
        self.assertTrue(matches('/home/michael/directory-trailing/'))

    def test_bracket_escapes(self):
        matches = _parse_gitignore_string(
            r'foo[\0].txt', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/foo0.txt'))
        self.assertFalse(matches(r'/home/michael/foo\.txt'))
        matches = _parse_gitignore_string(
            r'foo[1\-3\w].txt', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/foo1.txt'))
        self.assertFalse(matches('/home/michael/foo2.txt'))
        self.assertTrue(matches('/home/michael/foo3.txt'))
        self.assertTrue(matches('/home/michael/foo-.txt'))
        self.assertTrue(matches('/home/michael/foow.txt'))
        self.assertFalse(matches('/home/michael/fooq.txt'))

    def test_negated_bracket(self):
        matches = _parse_gitignore_string(
            r'foo[^1-3].txt', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/foo0.txt'))
        self.assertFalse(matches('/home/michael/foo1.txt'))
        self.assertFalse(matches('/home/michael/foo2.txt'))
        self.assertFalse(matches('/home/michael/foo3.txt'))
        self.assertTrue(matches('/home/michael/foo4.txt'))
        self.assertTrue(matches('/home/michael/foop.txt'))

        matches = _parse_gitignore_string(
            r'foo[!1-3].txt', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/foo0.txt'))
        self.assertFalse(matches('/home/michael/foo1.txt'))
        self.assertFalse(matches('/home/michael/foo2.txt'))
        self.assertFalse(matches('/home/michael/foo3.txt'))
        self.assertTrue(matches('/home/michael/foo4.txt'))
        self.assertTrue(matches('/home/michael/foop.txt'))

    def test_part_of_name(self):
        matches = _parse_gitignore_string(
            'build/', fake_base_dir='/home/michael')
        self.assertFalse(
            matches('/home/michael/folder1/folder2/extra_build/folder3/file.txt'))
        self.assertFalse(
            matches('/home/michael/folder1/folder2/extra_build.txt'))
        self.assertFalse(matches('/home/michael/folder1/build.txt'))
        self.assertFalse(matches('/home/michael/extra_build.txt'))
        self.assertFalse(matches('/home/michael/build.txt'))
        self.assertFalse(matches('/home/michael/build'))
        self.assertTrue(matches('/home/michael/build/'))
        self.assertTrue(matches('/home/michael/folder1/build/'))
        self.assertTrue(matches('/home/michael/folder1/build/folder2'))
        self.assertTrue(matches('/home/michael/folder1/build/file.txt'))
        self.assertTrue(
            matches('/home/michael/folder1/build/folder2/file.txt'))

    def test_trailing_slash(self):
        matches = _parse_gitignore_string(
            'build/    ', fake_base_dir='/home/michael')
        self.assertFalse(
            matches('/home/michael/folder1/folder2/extra_build/folder3/file.txt'))
        self.assertFalse(
            matches('/home/michael/folder1/folder2/extra_build.txt'))
        self.assertFalse(matches('/home/michael/folder1/build.txt'))
        self.assertFalse(matches('/home/michael/extra_build.txt'))
        self.assertFalse(matches('/home/michael/build.txt'))
        self.assertFalse(matches('/home/michael/build'))
        self.assertTrue(matches('/home/michael/build/'))

    def test_asterisk_folder(self):
        matches = _parse_gitignore_string(
            'foo*', fake_base_dir='/home/michael')
        self.assertTrue(matches('/home/michael/foo.txt'))
        self.assertTrue(matches('/home/michael/foo/bar.txt'))
        self.assertTrue(matches('/home/michael/fiz/foo.txt'))
        self.assertFalse(matches('/home/michael/fiz/bar.txt'))
        self.assertTrue(matches('/home/michael/fiz/foo/bar.txt'))
        self.assertTrue(matches('/home/michael/fiz/foo/bar/buz.txt'))

    def test_negation_complex(self):
        matches = _parse_gitignore_string("""
/foo/**/bar*
!/foo/bar
!barfiz/
foo/barfiz/buz
!fiz
        """, fake_base_dir='/home/michael')

        # git ignores this path even though `!fiz`?
        # self.assertFalse(matches('/home/michael/foo/fiz/bar'))

        self.assertFalse(matches('/home/michael/foo/bar/fiz'))

        # git ignores this path even though `!fiz`?
        # self.assertFalse(matches('/home/michael/foo/barfoo/fiz'))

        self.assertTrue(matches('/home/michael/foo/barfoo.txt'))
        self.assertFalse(matches('/home/michael/foo/barfiz/asdf.txt'))

        # git ignores this path even though `!fiz`?
        # self.assertFalse(matches('/home/michael/foo/fiz/barfiz/asdf.txt'))

        # git ignores this path even though `!fiz`?
        # self.assertFalse(matches('/home/michael/foo/fiz/barfiz/buz/asdf.txt'))

        self.assertTrue(matches('/home/michael/foo/barfiz/buz'))
        self.assertFalse(matches('/home/michael/foo/bar'))
        self.assertTrue(matches('/home/michael/foo/bar.txt'))

        # git ignores this path even though `!fiz`?
        # self.assertFalse(matches('/home/michael/foo/barfiz/buz/fiz'))

        self.assertFalse(matches('/home/michael/fiz/foo/barfiz/buz'))
        self.assertFalse(matches('/home/michael/asdf/foo/barfiz/buz'))

    def test_directory_only(self):
        matches = _parse_gitignore_string(
            'foo/',
            fake_base_dir='/home/michael',
            honor_directory_only=True)
        with patch('os.path.isdir', lambda path: True):
            self.assertTrue(matches('/home/michael/foo'))
        with patch('os.path.isdir', lambda path: False):
            self.assertFalse(matches('/home/michael/foo'))
            self.assertTrue(matches('/home/michael/foo/bar.txt'))

    def test_negated_directory_only(self):
        matches = _parse_gitignore_string(
            '**\n!foo/',
            fake_base_dir='/home/michael',
            honor_directory_only=True)
        with patch('os.path.isdir', lambda path: True):
            self.assertFalse(matches('/home/michael/foo'))
            self.assertFalse(matches('/home/michael/foo/'))
        with patch('os.path.isdir', lambda path: False):
            self.assertTrue(matches('/home/michael/foo'))
            self.assertFalse(matches('/home/michael/foo/bar.txt'))

    def test_supports_path_type_argument(self):
        matches = _parse_gitignore_string(
            'file1\n!file2', fake_base_dir='/home/michael')
        self.assertTrue(matches(Path('/home/michael/file1')))
        self.assertFalse(matches(Path('/home/michael/file2')))


def _parse_gitignore_string(
        data: str, fake_base_dir: str = None, honor_directory_only: bool = False):
    with patch('builtins.open', mock_open(read_data=data)):
        success = parse_gitignore(
            f'{fake_base_dir}/.gitignore',
            fake_base_dir,
            honor_directory_only)
        return success


if __name__ == '__main__':
    import unittest
    unittest.main()
