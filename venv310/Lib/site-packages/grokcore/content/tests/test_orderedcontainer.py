"""

The grokcore.content.OrderedContainer is a a model that is also a container.
Unlike plain grokcore.content Containers, OrderedContainers keep the mapping
keys in the order items were added. It has a dictionary API. It in fact
stores its information in a BTree so you can store a lot of items in a
scalable way.

  >>> from zope.container.interfaces import IContainer
  >>> bones = OrderedBones()
  >>> IContainer.providedBy(bones)
  True
  >>> from zope.container.interfaces import IOrderedContainer
  >>> IOrderedContainer.providedBy(bones)
  True
  >>> from zope.container.btree import BTreeContainer
  >>> isinstance(bones, BTreeContainer)
  True

Order is initially determined by the sequence in which items were added (mind
that there is a subscriber to the containermodified event in order to
illustrate an ordered container fires events just like normal containers)::

  >>> bones['thigh'] = Bone('Thigh Bone')
  >>> bones['knee'] = Bone('Knee Cap')
  >>> bones['shin'] = Bone('Shin Bone')
  >>> bones['ankle'] = Bone('Ankle Joint')
  >>> bones.keys()
  ['thigh', 'knee', 'shin', 'ankle']

Now change the order::

  >>> bones.updateOrder(order=['ankle', 'shin', 'knee', 'thigh'])
  >>> bones.keys()
  ['ankle', 'shin', 'knee', 'thigh']

  >>> list(bones.items())
  [('ankle', <grokcore.content.tests.test_orderedcontainer.Bone object at ...>),
  ('shin', <grokcore.content.tests.test_orderedcontainer.Bone object at ...>),
  ('knee', <grokcore.content.tests.test_orderedcontainer.Bone object at ...>),
  ('thigh', <grokcore.content.tests.test_orderedcontainer.Bone object at ...>)]

  >>> [bone.name for bone in bones.values()]
  ['Ankle Joint', 'Shin Bone', 'Knee Cap', 'Thigh Bone']

  >>> del bones['knee']
  >>> bones.keys()
  ['ankle', 'shin', 'thigh']

  >>> bones['toe'] = Bone('Toe')
  >>> bones.keys()
  ['ankle', 'shin', 'thigh', 'toe']

Adding a new object under an existing key, raises a DuplicationError::

  >>> bones['shin'] = Bone('Another Shin Bone')
  Traceback (most recent call last):
  ...
  KeyError: ...'shin'

Reordering with a wrong set of keys should fail::

  >>> bones.updateOrder(order=['ankle', 'shin', 'knee', 'thigh'])
  Traceback (most recent call last):
  ...
  ValueError: Incompatible key set.

Reordering will not corrupt the key-value mapping (there used to an edge case
where it was possible to corrupt the mapping)::

  >>> morebones = OrderedBones()
  >>> morebones['thigh'] = Bone('Thigh Bone')
  >>> morebones['knee'] = Bone('Knee Cap')
  >>> morebones['shin'] = Bone('Shin Bone')
  >>> morebones['ankle'] = Bone('Ankle Joint')
  >>> # There used to be a bug where this new order would have been
  >>> # accepted and thus would result in a corrupted _order listing
  >>> # in the OrderedContainer instance.
  >>> morebones.updateOrder(
  ...     order=['ankle', 'shin', 'knee', 'thigh', 'ankle', 'shin'])
  Traceback (most recent call last):
  ...
  ValueError: Incompatible key set.

The OrderedContainer is also an iterator which returns the keys:
  >>> [ bone for bone in morebones]
  ['thigh', 'knee', 'shin', 'ankle']

"""  # noqa: E501 line too long

from grokcore.content import Model
from grokcore.content import OrderedContainer


class OrderedBones(OrderedContainer):
    pass


class Bone(Model):
    def __init__(self, name):
        self.name = name


def test_suite():
    import doctest
    suite = doctest.DocTestSuite(
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS)
    return suite
