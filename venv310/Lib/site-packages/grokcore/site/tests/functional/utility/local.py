"""
Local Utilities can be registered on subclasses of grok.Site using
grok.local_utility:

  >>> cave = Cave()
  >>> getRootFolder()["cave"] = cave

  >>> from zope import component
  >>> from zope.component.hooks import getSite, setSite
  >>> setSite(cave)

  >>> fireplace = component.getUtility(IFireplace)
  >>> IFireplace.providedBy(fireplace)
  True
  >>> isinstance(fireplace, Fireplace)
  True

  >>> club = component.getUtility(IClub)
  >>> IClub.providedBy(club)
  True
  >>> isinstance(club, Club)
  True

  >>> spiky = component.getUtility(IClub, name='spiky')
  >>> IClub.providedBy(spiky)
  True
  >>> isinstance(spiky, SpikyClub)
  True

  >>> mammoth = component.getUtility(IMammoth)
  >>> IMammoth.providedBy(mammoth)
  True
  >>> isinstance(mammoth, Mammoth)
  True

  >>> tiger = component.getUtility(IMammoth, name='tiger')
  >>> IMammoth.providedBy(tiger)
  True
  >>> isinstance(tiger, SabretoothTiger)
  True

  >>> painting = component.getUtility(IPainting, name='blackandwhite')
  >>> IPainting.providedBy(painting)
  True
  >>> isinstance(painting, CavePainting)
  True

  >>> colored = component.getUtility(IPainting, name='color')
  >>> IPainting.providedBy(colored)
  True
  >>> isinstance(colored, ColoredCavePainting)
  True

Since it is a local utility, it is not available outside its site:

  >>> setSite(None)
  >>> component.getUtility(IFireplace)
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IFireplace>, '')

  >>> component.getUtility(IClub)
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IClub>, '')

  >>> component.getUtility(IClub, name='spiky')
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IClub>, 'spiky')

  >>> component.getUtility(IMammoth)
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IMammoth>, '')

  >>> component.getUtility(IMammoth, name='tiger')
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IMammoth>, 'tiger')

  >>> component.getUtility(IPainting, name='blackandwhite')
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IPainting>, 'blackandwhite')

  >>> component.getUtility(IPainting, name='color')
  Traceback (most recent call last):
    ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass grokcore.site.tests.functional.utility.local.IPainting>, 'color')
"""  # noqa: E501
import persistent
from zope import interface

import grokcore.site


class IFireplace(interface.Interface):
    pass


class IClub(interface.Interface):
    pass


class ISpiky(interface.Interface):
    pass


class IMammoth(interface.Interface):
    pass


@interface.implementer(IFireplace)
class Fireplace(grokcore.site.LocalUtility):
    pass


@interface.implementer(IClub)
class Club:
    pass


@interface.implementer(IClub, ISpiky)
class SpikyClub:
    pass


@interface.implementer(IMammoth, IClub)
class Mammoth(grokcore.site.LocalUtility):
    pass


@interface.implementer(IMammoth, IClub)
class SabretoothTiger(grokcore.site.LocalUtility):
    grokcore.site.provides(IMammoth)


class IPainting(persistent.interfaces.IPersistent):
    pass


@interface.implementer(IPainting)
class CavePainting(grokcore.site.LocalUtility):
    pass


@interface.implementer(IPainting)
class ColoredCavePainting(grokcore.site.LocalUtility):
    grokcore.site.provides(IPainting)


class Cave(grokcore.site.Site):
    grokcore.site.local_utility(Fireplace)
    grokcore.site.local_utility(Club)
    grokcore.site.local_utility(SpikyClub, provides=IClub, name='spiky')
    grokcore.site.local_utility(Mammoth, provides=IMammoth)
    grokcore.site.local_utility(SabretoothTiger, name='tiger')
    grokcore.site.local_utility(
        CavePainting, name='blackandwhite', provides=IPainting)
    grokcore.site.local_utility(ColoredCavePainting, name='color')
