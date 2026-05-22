from collective.ai import _
from zope.interface import provider
from zope.schema.interfaces import IVocabularyFactory
from zope.schema.vocabulary import SimpleTerm
from zope.schema.vocabulary import SimpleVocabulary


CAPABILITIES = (
    ("completion", _("Chat / Completion")),
    ("embedding", _("Embeddings")),
    ("vision", _("Vision")),
    ("tools", _("Function calling / Tools")),
    ("thinking", _("Reasoning / Thinking")),
)


@provider(IVocabularyFactory)
def capabilities_vocabulary(context):
    """Fixed vocabulary of AI model capabilities.

    Token values match Ollama's `/api/show` capability strings so that they
    can be passed straight through to the model filter without translation.
    """
    return SimpleVocabulary([
        SimpleTerm(value=value, token=value, title=title)
        for value, title in CAPABILITIES
    ])
