import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctfagent.race import (  # noqa: E402
    difficulty_rank, rank_challenges, rank_key, split_challenges,
)

CAT = {2: "Web", 3: "Crypto", 4: "Reversing", 5: "Pwn", 6: "Forensics", 7: "Misc"}


def ch(cid, difficulty, points, cat=7, name=None):
    return {"id": cid, "difficulty": difficulty, "points": points,
            "challenge_category_id": cat, "name": name or f"c{cid}"}


def ten():
    # a realistic spread: ids deliberately out of rank order
    return [
        ch(101, "easy", 300, 2),       # web easy
        ch(102, "insane", 1000, 5),    # pwn insane
        ch(103, "medium", 500, 3),     # crypto medium
        ch(104, "very easy", 150, 2),  # web very easy  <- easiest
        ch(105, "hard", 800, 4),       # rev hard
        ch(106, "easy", 350, 6),       # forensics easy
        ch(107, "medium", 450, 2),     # web medium
        ch(108, "hard", 750, 5),       # pwn hard
        ch(109, "very easy", 200, 3),  # crypto very easy
        ch(110, "medium", 500, 5),     # pwn medium (same diff+pts as 103, slower cat)
    ]


class DifficultyRankTest(unittest.TestCase):
    def test_order(self):
        order = [difficulty_rank(ch(1, d, 0)) for d in
                 ("very easy", "easy", "medium", "hard", "insane")]
        self.assertEqual(order, [0, 1, 2, 3, 4])

    def test_unknown_label_is_medium(self):
        self.assertEqual(difficulty_rank(ch(1, "spicy", 0)), 2)
        self.assertEqual(difficulty_rank(ch(1, "", 0)), 2)


class RankTest(unittest.TestCase):
    def test_difficulty_dominates(self):
        ranked = rank_challenges(ten(), CAT)
        diffs = [difficulty_rank(c) for c in ranked]
        self.assertEqual(diffs, sorted(diffs))

    def test_points_break_same_difficulty(self):
        a, b = ch(1, "medium", 400, 7), ch(2, "medium", 600, 7)
        self.assertLess(rank_key(a, CAT), rank_key(b, CAT))

    def test_category_breaks_same_difficulty_and_points(self):
        web, pwn = ch(1, "medium", 500, 2), ch(2, "medium", 500, 5)
        ranked = rank_challenges([pwn, web], CAT)
        self.assertEqual([c["id"] for c in ranked], [1, 2])  # web before pwn

    def test_two_easiest_are_very_easy(self):
        ranked = rank_challenges(ten(), CAT)
        self.assertEqual({ranked[0]["id"], ranked[1]["id"]}, {104, 109})


class SplitTest(unittest.TestCase):
    def test_five_five_disjoint_and_complete(self):
        us, paul = split_challenges(ten(), ours=5, easiest_to_us=2, cat_names=CAT)
        self.assertEqual(len(us), 5)
        self.assertEqual(len(paul), 5)
        us_ids, paul_ids = {c["id"] for c in us}, {c["id"] for c in paul}
        self.assertEqual(us_ids & paul_ids, set())
        self.assertEqual(us_ids | paul_ids, {c["id"] for c in ten()})

    def test_two_easiest_go_to_us(self):
        us, _ = split_challenges(ten(), ours=5, easiest_to_us=2, cat_names=CAT)
        self.assertEqual({us[0]["id"], us[1]["id"]}, {104, 109})

    def test_fewer_than_target(self):
        few = ten()[:3]
        us, paul = split_challenges(few, ours=5, easiest_to_us=2, cat_names=CAT)
        self.assertEqual(len(us), 3)
        self.assertEqual(paul, [])
        self.assertEqual({c["id"] for c in us}, {c["id"] for c in few})

    def test_no_reservation_pure_alternation(self):
        us, paul = split_challenges(ten(), ours=5, easiest_to_us=0, cat_names=CAT)
        self.assertEqual(len(us), 5)
        self.assertEqual(len(paul), 5)

    def test_deterministic(self):
        a = split_challenges(ten(), cat_names=CAT)
        b = split_challenges(ten(), cat_names=CAT)
        self.assertEqual([c["id"] for c in a[0]], [c["id"] for c in b[0]])
        self.assertEqual([c["id"] for c in a[1]], [c["id"] for c in b[1]])


if __name__ == "__main__":
    unittest.main()
