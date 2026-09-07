"""
A grok.EditForm uses applyData in update mode to save the form data on
the object.  Update mode means that only those fields are changed on
the object that need to be changed.

This is essentially the same narrative as 'editform_applydata'. Here we
test the whole procedure on fields on the interface implemented by the
model class:

  >>> getRootFolder()["manfred"] = mammoth = Mammoth()
  >>> mammoth.name = 'Manfred the Mammoth'
  >>> mammoth.size = 'Really big'

  >>> from zope.testbrowser.wsgi import Browser
  >>> browser = Browser()
  >>> browser.handleErrors = False

If we don't change any of the fields, there will no object modified
event and applyData will report no changes:

  >>> browser.open("http://localhost/manfred/@@edit")
  >>> browser.getControl("Apply").click()
  >>> 'No changes' in browser.contents
  True

If we change one field, only that attribute will be changed.  The
object modified event also reflects that:

  >>> browser.getControl(name="form.name").value = "Manfred the Big Mammoth"
  >>> browser.getControl("Apply").click()
  An IObjectModifiedEvent was sent for a mammoth with the following changes:
  name
  >>> 'Updated' in browser.contents
  True

Let's change the other field:

  >>> browser.getControl(name="form.size").value = "Enormously big"
  >>> browser.getControl("Apply").click()
  An IObjectModifiedEvent was sent for a mammoth with the following changes:
  size
  >>> 'Updated' in browser.contents
  True

And finally let's change both fields:

  >>> browser.getControl(name="form.name").value = "Manfred the Mammoth"
  >>> browser.getControl(name="form.size").value = "Really big"
  >>> browser.getControl("Apply").click()
  An IObjectModifiedEvent was sent for a mammoth with the following changes:
  name, size
  >>> 'Updated' in browser.contents
  True

"""
from zope import schema
from zope.interface import Interface
from zope.interface import implementer
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

import grokcore.formlib as grok


class IMammoth(Interface):
    name = schema.TextLine(title="Name")
    size = schema.TextLine(title="Size", default="Quite normal")


@implementer(IMammoth)
class Mammoth(grok.testing.Model):
    grok.testing.protect_get(grok.Public, 'name', 'size')
    grok.testing.protect_set(grok.Public, 'name', 'size')


class Edit(grok.EditForm):
    pass


@grok.subscribe(Mammoth, IObjectModifiedEvent)
def notify_change_event(mammoth, event):
    print("An IObjectModifiedEvent was sent for a mammoth with the "
          "following changes:")
    for descr in event.descriptions:
        print(", ".join(descr.attributes))
