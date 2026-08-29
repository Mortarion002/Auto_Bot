from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from reddit_scraper import ATOM_NS, _parse_atom_entry


def _entry(author_name: str) -> ET.Element:
    xml = f"""
    <entry xmlns="{ATOM_NS}">
      <id>t3_abc123</id>
      <title>Looking for a Delighted alternative</title>
      <link href="https://www.reddit.com/r/SaaS/comments/abc123/example/" />
      <author><name>{author_name}</name></author>
      <published>2026-04-29T08:00:00+00:00</published>
      <content type="html">&lt;p&gt;body text&lt;/p&gt;</content>
    </entry>
    """
    return ET.fromstring(xml)


class ParseAtomEntryAuthorTests(unittest.TestCase):
    def test_slash_u_prefix_is_stripped_without_eating_leading_letters(self) -> None:
        post = _parse_atom_entry(_entry("/u/underscore_guy"), "SaaS")
        assert post is not None
        self.assertEqual(post.author, "underscore_guy")

    def test_username_starting_with_u_is_preserved(self) -> None:
        post = _parse_atom_entry(_entry("/u/usama"), "SaaS")
        assert post is not None
        self.assertEqual(post.author, "usama")

    def test_legacy_user_prefix_is_stripped(self) -> None:
        post = _parse_atom_entry(_entry("/user/urban_dev"), "SaaS")
        assert post is not None
        self.assertEqual(post.author, "urban_dev")

    def test_bare_username_is_left_alone(self) -> None:
        post = _parse_atom_entry(_entry("plain_name"), "SaaS")
        assert post is not None
        self.assertEqual(post.author, "plain_name")

    def test_missing_author_falls_back_to_deleted(self) -> None:
        post = _parse_atom_entry(_entry(""), "SaaS")
        assert post is not None
        self.assertEqual(post.author, "[deleted]")


if __name__ == "__main__":
    unittest.main()
