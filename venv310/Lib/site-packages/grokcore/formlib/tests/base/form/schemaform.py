"""
A grok.Model may implement one or more interfaces that are schemas:

  >>> grok.testing.grok(__name__)
  >>> manfred = Mammoth()
  >>> print(manfred.name)
  None
  >>> print(manfred.size)
  Quite normal

A grok.EditForm is a special grok.View that renders an edit form.

  >>> from zope import component
  >>> from zope.publisher.browser import TestRequest
  >>> request = TestRequest()
  >>> view = component.getMultiAdapter((manfred, request), name='edit')
  >>> len(view.form_fields)
  2
  >>> [w.__name__ for w in view.form_fields]
  ['name', 'size']

When there are multiple schemas in play, we get all the fields:

  >>> view = component.getMultiAdapter((Manfred(), request), name='edit2')
  >>> len(view.form_fields)
  3
  >>> [w.__name__ for w in view.form_fields]
  ['can_talk', 'name', 'size']

If the context is an interface instead of a model directly, the fields
will be retrieved from that interface, and that interface only:

  >>> view = component.getMultiAdapter(
  ...   (YetAnotherMammoth(), request), name='edit4')
  >>> len(view.form_fields)
  2
  >>> [w.__name__ for w in view.form_fields]
  ['alpha', 'beta']

"""
from zope import schema
from zope.interface import Interface
from zope.interface import implementer
from zope.schema.fieldproperty import FieldProperty

import grokcore.formlib as grok


class IMammoth(Interface):
    name = schema.TextLine(title="Name")
    size = schema.TextLine(title="Size", default="Quite normal")


@implementer(IMammoth)
class Mammoth(grok.Context):

    name = FieldProperty(IMammoth['name'])
    size = FieldProperty(IMammoth['size'])


class Edit(grok.EditForm):
    grok.context(Mammoth)


class IMovieCharacter(Interface):
    can_talk = schema.Bool(title='Can talk', default=False)


@implementer(IMovieCharacter)
class Manfred(Mammoth):
    pass


class Edit2(grok.EditForm):
    grok.context(Manfred)


class IYetAnotherMammoth(Interface):
    alpha = schema.TextLine(title='alpha')
    beta = schema.TextLine(title='beta')


@implementer(IYetAnotherMammoth)
class YetAnotherMammoth(grok.Context):
    pass


class Edit4(grok.EditForm):
    grok.context(IYetAnotherMammoth)
