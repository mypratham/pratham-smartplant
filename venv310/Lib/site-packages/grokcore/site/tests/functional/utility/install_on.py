"""
Local Utilities can be registered on subclasses of grok.Site using
grok.local_utility but only on grok.install_on:

  >>> cave = Cave()
  >>> getRootFolder()['cave'] = cave

  >>> from zope.component import queryUtility
  >>> from zope.component.hooks import setSite
  >>> from zope.event import notify
  >>> setSite(cave)

  >>> club = queryUtility(IClub)
  >>> club is None
  True

  >>> notify(PartyEvent(cave))
  >>> club = queryUtility(IClub)
  >>> IClub.providedBy(club)
  True
"""
from zope.interface import Interface
from zope.interface import implementer
from zope.interface.interfaces import IObjectEvent
from zope.interface.interfaces import ObjectEvent

import grokcore.site


class IPartyEvent(IObjectEvent):
    pass


@implementer(IPartyEvent)
class PartyEvent(ObjectEvent):
    pass


class IClub(Interface):
    pass


@implementer(IClub)
class Club(grokcore.site.LocalUtility):
    pass


class Cave(grokcore.site.Site):
    grokcore.site.install_on(IPartyEvent)
    grokcore.site.local_utility(Club)
