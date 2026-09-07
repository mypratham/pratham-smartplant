"""
A grok.Model may implement a schema that inherits from another one:

  >>> grok.testing.grok(__name__)
  >>> manfred = Mammoth()

  >>> from zope import component
  >>> from zope.publisher.browser import TestRequest
  >>> request = TestRequest()

Without AutoFields, just a simple edit form:

  >>> view = component.getMultiAdapter((manfred, request), name='edit')
  >>> len(view.form_fields)
  3
  >>> [w.__name__ for w in view.form_fields]
  ['name', 'size', 'speciality']

With AutoFields:

  >>> view = component.getMultiAdapter((manfred, request), name='edit2')
  >>> len(view.form_fields)
  3
  >>> [w.__name__ for w in view.form_fields]
  ['name', 'size', 'speciality']

  >>> antimanfred = YetAnotherMammoth()
  >>> view = component.getMultiAdapter((antimanfred, request), name='edit3')
  >>> len(view.form_fields)
  3
  >>> [w.__name__ for w in view.form_fields]
  ['name', 'size', 'speciality']
"""
from zope import schema
from zope.interface import Interface
from zope.interface import implementer

import grokcore.formlib as grok


class IMammoth(Interface):
    name = schema.TextLine(title="Name")
    size = schema.TextLine(title="Size", default="Quite normal")


class ISpecialMammoth(IMammoth):
    speciality = schema.TextLine(title="Speciality")


@implementer(ISpecialMammoth)
class Mammoth(grok.Context):
    pass


class Edit(grok.EditForm):
    grok.context(Mammoth)


class Edit2(grok.EditForm):
    grok.context(Mammoth)

    form_fields = grok.AutoFields(Mammoth)


# situation where subclass implements something on top of base class
@implementer(IMammoth)
class AnotherMammoth(grok.Context):
    pass


@implementer(ISpecialMammoth)
class YetAnotherMammoth(AnotherMammoth):
    pass


class Edit3(grok.EditForm):
    grok.context(YetAnotherMammoth)
