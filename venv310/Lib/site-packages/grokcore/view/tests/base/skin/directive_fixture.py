from zope import interface

import grokcore.view as grok


class IIsAnInterface(interface.Interface):
    grok.skin('skin_name')
