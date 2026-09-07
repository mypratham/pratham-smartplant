from zope.interface import Attribute
from zope.interface import Interface
from zope.interface import implementer


class IHandleExceptionEvent(Interface):
    """Event fired when handling an exception."""

    request = Attribute('The current request')


@implementer(IHandleExceptionEvent)
class HandleExceptionEvent:

    def __init__(self, request):
        self.request = request
