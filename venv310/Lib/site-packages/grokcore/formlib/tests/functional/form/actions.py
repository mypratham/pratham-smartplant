"""
Using the @grok.action decorator, different actions can be defined on
a grok.Form. When @grok.action is used, the default behaviour (the
'Apply' action) is not available anymore, but it can triggered
manually by calling self.applyData(object, data).

  >>> getRootFolder()["manfred"] = Mammoth()

  >>> from zope.testbrowser.wsgi import Browser
  >>> browser = Browser()
  >>> browser.handleErrors = False
  >>> browser.open("http://localhost/manfred/@@edit")
  >>> browser.getControl(name="form.name").value = "Manfred the Mammoth"
  >>> browser.getControl(name="form.size").value = "Really big"
  >>> browser.getControl("Apply").click()
  >>> print(browser.contents)
  <html>...
  ...Modified!...
  ...Manfred the Mammoth...
  ...Really big...
  ...

Save again without any changes:

  >>> browser.getControl("Apply").click()
  >>> print(browser.contents)
  <html>...
  ...No changes!...
  ...

  >>> browser.open("http://localhost/manfred/@@edit")
  >>> browser.getControl(name="form.name").value = "Manfred the Second"
  >>> browser.getControl("Hairy").click()
  >>> print(browser.contents)
  <html>...
  ...Manfred the Second...
  ...Really big and hairy...
  ...

  >>> browser.open("http://localhost/manfred/meet")
  >>> browser.getControl(name="form.other").value = "Ellie"
  >>> browser.getControl("Meet").click()
  >>> print(browser.contents)
  Manfred the Second meets Ellie

There used to be a bug (or rather an inconvenience) where when no actions were
defined, the template used for rendering a Form component would fail expecting
to find an actions attribute on the component. This is fixed now and thus the
following view does not raise an AttributeError anymore::

  >>> browser.open("http://localhost/manfred/greet")

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
class Mammoth(grok.testing.Model):
    grok.testing.protect_get(grok.Public, 'name', 'size')
    grok.testing.protect_set(grok.Public, 'name', 'size')

    name = FieldProperty(IMammoth['name'])
    size = FieldProperty(IMammoth['size'])


class Edit(grok.EditForm):

    @grok.action("Apply")
    def handle_apply(self, **data):
        if self.applyData(self.context, **data):
            self.status = 'Modified!'
        else:
            self.status = 'No changes!'

    @grok.action("Hairy")
    def handle_hairy(self, **data):
        self.applyData(self.context, **data)
        self.context.size += " and hairy"


class Meet(grok.Form):
    form_fields = grok.Fields(
        other=schema.TextLine(title='Mammoth to meet with'))

    @grok.action('Meet')
    def meet(self, other):
        return self.context.name + ' meets ' + other


class Greet(grok.Form):
    form_fields = grok.Fields(
        other=schema.TextLine(title='Mammoth to say hi to'))
