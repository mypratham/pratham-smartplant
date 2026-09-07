"""
Mind that there is a subscriber to the containermodified event in order to
illustrate an ordered container fires events just like normal containers::

  >>> from grokcore.component import testing
  >>> testing.grok(__name__)
  >>> bones = OrderedBones()

Add an item::

  >>> bones['thigh'] = Bone('Thigh Bone')
  Container has changed!

Now change the order::

  >>> bones.updateOrder(order=['thigh'])
  Container has changed!

Delete an item::

  >>> del bones['thigh']
  Container has changed!
  >>> bones.keys()
  []

"""

from grokcore.component import subscribe
from zope.container.interfaces import IContainerModifiedEvent

from grokcore.content import Model
from grokcore.content import OrderedContainer


class OrderedBones(OrderedContainer):
    pass


class Bone(Model):
    def __init__(self, name):
        self.name = name


@subscribe(OrderedBones, IContainerModifiedEvent)
def container_changed(object, event):
    print('Container has changed!')


def test_suite():
    import doctest

    import zope.component.eventtesting
    from zope.testing import cleanup

    def cleanUp(test):
        cleanup.cleanUp()

    suite = doctest.DocTestSuite(
        setUp=zope.component.eventtesting.setUp,
        tearDown=cleanUp,
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS)
    return suite
