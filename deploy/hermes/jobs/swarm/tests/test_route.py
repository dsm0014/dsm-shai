"""Tier routing (spec 13): pure function, no model call. The tier comes only from the tag, the local failure count and
the task-wide orchestrator mode."""
import inspect, unittest

import helpers  # noqa: F401  (puts the swarm directory on sys.path)
import route


class Routing(unittest.TestCase):
    def test_hard_step_goes_to_haiku(self):
        self.assertEqual(route.route("hard", 0, "haiku"), "haiku")

    def test_normal_step_goes_to_chat(self):
        self.assertEqual(route.route("normal", 0, "haiku"), "chat")

    def test_normal_step_with_two_local_failures_goes_to_haiku(self):
        self.assertEqual(route.route("normal", 2, "haiku"), "haiku")

    def test_normal_step_with_one_local_failure_stays_on_chat(self):
        self.assertEqual(route.route("normal", 1, "haiku"), "chat")

    def test_orchestrator_chat_is_always_chat(self):
        self.assertEqual(route.route("hard", 0, "chat"), "chat")
        self.assertEqual(route.route("hard", 5, "chat"), "chat")
        self.assertEqual(route.route("normal", 2, "chat"), "chat")

    def test_default_orchestrator_is_haiku_for_hard_steps(self):
        self.assertEqual(route.route("hard", 0), "haiku")

    def test_signature_is_exactly_tag_failures_orchestrator(self):
        params = list(inspect.signature(route.route).parameters)
        self.assertEqual(params[:2], ["tag", "local_failures"])
        self.assertEqual(params[2], "orchestrator")
        self.assertEqual(len(params), 3)

    def test_tags_are_normal_and_hard(self):
        self.assertEqual(route.TAGS, ("normal", "hard"))


if __name__ == "__main__":
    unittest.main()
