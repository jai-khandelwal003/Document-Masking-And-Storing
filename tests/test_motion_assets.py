from tests import _isolation  # noqa: F401  (must be first: isolates test data)

import base64
import os
import re
import unittest

from app import create_app

STATIC = os.path.join(os.path.dirname(__file__), "..", "app", "static")
PUBLISHABLE_KEY = "pk_test_" + base64.b64encode(b"clerk.example.com$").decode()


def read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as handle:
        return handle.read()


class MotionAssetTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, AUTH_PROVIDER="local", USER_PASSWORD="a-long-test-passphrase")
        self.client = self.app.test_client()

    def login(self, client=None):
        client = client or self.client
        with client.session_transaction() as sess:
            sess["auth_user"] = "test-user"

    def test_assets_are_served_without_login_and_allowed_by_csp(self):
        anon = self.app.test_client()
        css = anon.get("/static/motion.css")
        js = anon.get("/static/motion.js")
        self.assertEqual((css.status_code, js.status_code), (200, 200))
        self.assertIn("text/css", css.mimetype)
        self.assertIn("javascript", js.mimetype)
        csp = css.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("style-src 'self'", csp)

    def test_every_page_loads_the_stylesheet(self):
        self.login()
        pages = {
            "/login": self.app.test_client().get("/login"),
            "/dashboard": self.client.get("/dashboard"),
            "/identity/view": self.client.get("/identity/view"),
        }
        self.app.config.update(AUTH_PROVIDER="clerk", CLERK_PUBLISHABLE_KEY=PUBLISHABLE_KEY, CLERK_SECRET_KEY="sk_test_dummy")
        pages["clerk /login"] = self.app.test_client().get("/login")
        for name, response in pages.items():
            self.assertIn("/static/motion.css", response.get_data(as_text=True), name)

    def test_dashboard_loads_the_script_deferred(self):
        self.login()
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertRegex(html, r'<script src="/static/motion\.js\?v=\d+" defer></script>')

    def test_stylesheet_respects_reduced_motion(self):
        css = read("motion.css")
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        block = css[css.index("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("animation-duration: 0.001ms !important", block)
        self.assertIn("transition-duration: 0.001ms !important", block)

    def test_script_respects_reduced_motion_and_cannot_break_the_page(self):
        js = read("motion.js")
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn("catch (error)", js)
        self.assertIn('"use strict"', js)

    def test_script_has_no_dynamic_code_execution_or_inline_html(self):
        js = read("motion.js")
        for forbidden in ("eval(", "new Function", "innerHTML", "document.write", "setTimeout(\""):
            self.assertNotIn(forbidden, js)

    def test_entrance_animations_do_not_pin_transforms(self):
        css = read("motion.css")
        for line in css.splitlines():
            if re.search(r"animation:\s*m-(rise|pop)\b", line) and "infinite" not in line:
                self.assertNotRegex(line, r"\b(both|forwards)\b", line)

    def test_every_animation_name_used_is_defined(self):
        css = read("motion.css")
        defined = set(re.findall(r"@keyframes\s+([\w-]+)", css))
        used = set()
        for value in re.findall(r"animation:\s*([^;]+);", css):
            used.update(re.findall(r"(?<![\w-])(m-[\w-]+)", value))  # skips CSS variables such as --m-ease
        self.assertEqual(used - defined, set())

    def test_generic_selectors_are_scoped_so_they_cannot_override_the_dashboard(self):
        # Regression: an unscoped `.wrap > .panel` rule replaced the dashboard's own `.fade-up`
        # animation, leaving every dashboard panel at opacity 0 (an invisible page).
        css = read("motion.css")
        for line in css.splitlines():
            if re.match(r"\s*\.(wrap|docs)\b", line):
                self.fail(f"unscoped page-specific selector: {line.strip()}")
        self.assertIn('body[data-page="identity"] .wrap > .panel', css)
        self.login()
        identity = self.client.get("/identity/view").get_data(as_text=True)
        self.assertIn('<body data-page="identity">', identity)
        self.assertNotIn("data-page=", self.client.get("/dashboard").get_data(as_text=True))

    def test_stylesheet_never_animates_the_dashboards_fade_up_panels(self):
        css = read("motion.css")
        for block in re.findall(r"([^{}]+)\{([^{}]*animation:[^{}]*)\}", css):
            selector = block[0].strip()
            if selector.startswith(("@", "from", "to")) or re.match(r"^\d", selector):
                continue
            self.assertNotRegex(selector, r"(?<![\w-])\.panel\b(?!.*\[data-page)", f"{selector} would override .fade-up")

    def test_clerk_page_has_busy_and_done_states(self):
        self.app.config.update(AUTH_PROVIDER="clerk", CLERK_PUBLISHABLE_KEY=PUBLISHABLE_KEY, CLERK_SECRET_KEY="sk_test_dummy")
        html = self.app.test_client().get("/login").get_data(as_text=True)
        self.assertIn('class="msg busy"', html)
        self.assertIn("'done'", html)
        self.assertIn("prefers-reduced-motion", html)


if __name__ == "__main__":
    unittest.main()
