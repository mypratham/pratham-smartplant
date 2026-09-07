import grokcore.component as grok

from grokcore.message import IMessageSource
from grokcore.message import PersistentMessage


@grok.implementer(IMessageSource)
class UniqueMessageSource(grok.GlobalUtility):
    """A source that handles a unique message.
    """
    grok.baseclass()
    grok.provides(IMessageSource)

    message = None

    def send(self, message, type='message'):
        self.message = PersistentMessage(message, type)

    def list(self, type=None):
        if self.message is None:
            return
        if type is None or self.message.type == type:
            yield self.message

    def delete(self, message):
        if message is self.message:
            self.message = None
        else:
            raise KeyError(message)
