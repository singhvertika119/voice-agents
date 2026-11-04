"""Reading a whole website (D-110): page order, what is kept from each page, and the shared menu/footer kept once."""
import pytest

from ingestion import site
from ingestion.parsers import ParseError

FRAME = ("<header><nav><a href='/'>Home</a> <a href='/products'>Products and services</a></nav></header>{}"
         "<footer><p>Sunrise Clinic, 12 MG Road, Jaipur</p><p>Call +91 98765 43210</p></footer>")


def page(title, body):
    return f"<html><head><title>{title} | Sunrise</title></head><body>{FRAME.format('<main>' + body + '</main>')}</body></html>"


def test_frame_is_kept_once_and_page_content_stays_whole():
    pages = [
        ("https://sunrise.in/", page("Home", "<h1>Welcome</h1><p>We treat families across Jaipur since 2001.</p>")),
        ("https://sunrise.in/fees", page("Fees", "<h2>Consultation</h2><p>Consultation costs 500 rupees.</p>")),
        ("https://sunrise.in/contact", page("Contact", "<h2>Our location</h2><p>Sunrise Clinic, 12 MG Road, Jaipur</p>")),
    ]
    md = site.extract_site(pages).markdown
    assert md.count("Call +91 98765 43210") == 1                      # footer once, not three times
    assert "# On every page of the website" in md
    contact = md[md.index("(/contact)"):]
    assert "Sunrise Clinic, 12 MG Road, Jaipur" in contact.split("\n# ")[0]   # the contact page keeps its own address
    assert "Consultation costs 500 rupees." in md
    assert "#### Consultation" in md or "### Consultation" in md


def test_hidden_and_form_text_is_left_out():
    html = page("Contact", "<p>Open Monday to Saturday, nine to seven.</p><form><label>Full Name *</label><input></form>"
                           "<div style='display: none'>Old timings ten to six</div>")
    md = site.extract_site([("https://sunrise.in/contact", html)]).markdown
    assert "Open Monday to Saturday" in md
    assert "Full Name" not in md and "Old timings" not in md


def test_lone_menu_words_dropped_but_numbers_kept():
    assert not site._keep("Products")
    assert site._keep("Rs 500")
    assert site._keep("## Fees")
    assert site._keep("Open on Sundays")


def test_empty_site_gives_readable_error():
    with pytest.raises(ParseError, match="JavaScript"):
        site.extract_site([("https://x.in/", "<html><body><script>app()</script></body></html>")])


def test_only_same_site_pages_that_callers_need():
    host = "sunrise.in"
    assert site._wanted("https://www.sunrise.in/fees", host, "")
    assert not site._wanted("https://other.in/fees", host, "")
    assert not site._wanted("https://sunrise.in/login", host, "")
    assert not site._wanted("https://sunrise.in/privacy-policy", host, "")
    assert not site._wanted("https://sunrise.in/brochure.pdf", host, "")
    assert not site._wanted("https://sunrise.in/blog/post", host, "/fees")   # a deeper start page keeps its own branch


def test_key_pages_first_then_menu_order_then_blog_last():
    start = "https://sunrise.in/"
    menu = ["https://sunrise.in/services", "https://sunrise.in/doctors"]
    urls = ["https://sunrise.in/blog/price-guide", "https://sunrise.in/doctors", "https://sunrise.in/contact-us",
            "https://sunrise.in/services", "https://sunrise.in/glossary/contactless", "https://sunrise.in/a/b/deep"]
    order = site._order(urls, start, menu)
    assert order[0] == "https://sunrise.in/contact-us"
    assert order.index("https://sunrise.in/services") < order.index("https://sunrise.in/doctors") < order.index("https://sunrise.in/a/b/deep")
    assert order[-1] == "https://sunrise.in/blog/price-guide"
    assert order.index("https://sunrise.in/glossary/contactless") > order.index("https://sunrise.in/doctors")
