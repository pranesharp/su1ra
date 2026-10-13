"""Diagnostic: what does WebKitGTK actually do when a link is clicked inside the
in-app browser pane?

Run:
    .venv/bin/python report/report/link-probe.py

It opens a window with the same kind of sandboxed iframe the app uses, pointed at
a Bing search. Click a result link, then read the terminal.

We log EVERY navigation-related signal WebKitGTK offers, so we can see which one
(if any) fires on the click:
  - create              (new-window request)
  - decide-policy       (navigation policy decision, incl. _blank)
  - load-changed        (a load started/committed/finished)
  - new-window-request  (if present)

Whichever fires tells us where to hook. If NONE fire, WebKit is swallowing the
click entirely and the fix has to be a JS interceptor inside the page.
"""

import gi

gi.require_version("WebKit2", "4.1")
from gi.repository import WebKit2, Gtk, GLib  # noqa: E402

HTML = """
<!doctype html><html><body style="margin:0;font:13px monospace;background:#111;color:#eee">
<div style="padding:6px">click a result link below — watch the terminal</div>
<iframe src="https://www.bing.com/search?q=laplace+transform"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
        style="width:100%;height:88vh;border:0"></iframe>
</body></html>
"""


def main():
    win = Gtk.Window(title="Su1ra link probe")
    win.set_default_size(900, 700)
    view = WebKit2.WebView()
    view.load_html(HTML, "http://localhost/")

    def log(*a):
        print("[probe]", *a, flush=True)

    def on_create(_view, action):
        try:
            uri = action.get_request().get_uri()
        except Exception as exc:
            uri = f"<err {exc}>"
        log("CREATE fired  uri=", uri)
        return None

    def on_decide(_view, decision, _dtype):
        try:
            if isinstance(decision, WebKit2.NavigationPolicyDecision):
                act = decision.get_navigation_action()
                log("DECIDE-POLICY  frame=", act.get_frame_name(),
                    "uri=", act.get_request().get_uri())
        except Exception as exc:
            log("DECIDE-POLICY err", exc)
        return False

    def on_load_changed(_view, event):
        log("LOAD-CHANGED", event.value_nick, "uri=", _view.get_uri())

    view.connect("create", on_create)
    view.connect("decide-policy", on_decide)
    view.connect("load-changed", on_load_changed)

    # Some WebKit builds expose a new-window-request signal; log it if present.
    try:
        view.connect("new-window-request", lambda v, r: log("NEW-WINDOW-REQUEST", r.get_uri()))
        log("connected new-window-request")
    except Exception:
        log("no new-window-request signal on this build")

    win.add(view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    log("ready — click a result link now")
    Gtk.main()


if __name__ == "__main__":
    main()
