from zope.interface import Interface

import grokcore.view as grok


some_obj = object()


class BogusSkin(Interface):
    grok.skin(some_obj)
