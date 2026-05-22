from collective.ai.interfaces import IAIService
from html import escape
from plone.app.textfield.value import RichTextValue
from zope.component import queryUtility


RICHTEXT_FIELD = "text"
PROMPT_TEMPLATE = (
    "Write a three paragraph story about the following subject: {title}. "
    "Separate the paragraphs with a blank line and return only the story, "
    "without any introduction or extra commentary."
)


def _to_html(content: str) -> str:
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [content.strip()]
    return "\n".join(f"<p>{escape(p)}</p>" for p in paragraphs)


def generate_story_on_create(obj, event):
    """Populate the rich text field with an AI-generated story."""
    title = getattr(obj, "title", None)
    if not title or not hasattr(obj, RICHTEXT_FIELD):
        return

    current = getattr(obj, RICHTEXT_FIELD, None)
    raw = getattr(current, "raw", "") if current is not None else ""
    if raw and raw.strip():
        return

    service = queryUtility(IAIService)
    if service is None:
        return

    story = service.chat(PROMPT_TEMPLATE.format(title=title), context=obj)
    if not story:
        return

    setattr(
        obj,
        RICHTEXT_FIELD,
        RichTextValue(_to_html(story), "text/html", "text/html"),
    )
