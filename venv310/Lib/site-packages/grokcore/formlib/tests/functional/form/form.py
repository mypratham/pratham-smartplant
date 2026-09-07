"""
A grok.EditForm is a special grok.View that renders an edit form.

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
  ...Manfred the Mammoth...
  ...Really big...
  ...

grok.DisplayForm renders a display form:

  >>> browser.open("http://localhost/manfred/@@display")
  >>> print(browser.contents)
  <html>...
  ...Manfred the Mammoth...
  ...Really big...
  ...

"Protected" forms only validate and process request data for the given
HTTP verb - usually POST. In addition, CSRF protection can be enabled.

"Submitting" the form over GET parameters should result in an
MethodNotAllowed error as the form is configured to only allow submits
over POST requests::

  >>> browser.open(
  ...    "http://localhost/manfred/@@editprotected?"
  ...    "form.name=Manfred&form.size=Big&form.actions.apply=Apply")
  Traceback (most recent call last):
  ...
  zope.publisher.interfaces.http.MethodNotAllowed: \
  <grokcore.formlib.tests.functional.form.form.Mammoth object at ...>, \
  <zope.publisher.browser.BrowserRequest instance \
  URL=http://localhost/manfred/@@editprotected>

When CSRF protection is enabled, the corresponding hidden form field is
rendered by the form templates::

  >>> browser.open("http://localhost/manfred/@@editcsrfprotected")
  >>> print(browser.contents)
  <html>...
  <input type="hidden" name="__csrftoken__" value="..." />...

  >>> browser.cookies['__csrftoken__'] in browser.contents
  True

Submitting the form with a wrong token or a missing token, will raise an
InvalidForm error::

  >>> browser.open("http://localhost/manfred/@@editcsrfprotected")
  >>> browser.getControl(name="form.name").value = "Manfred the Mammoth"
  >>> browser.getControl(name="form.size").value = "Really big"
  >>> browser.getControl(name="__csrftoken__").value = "invalid value"
  >>> browser.getControl("Apply").click()
  Traceback (most recent call last):
  ...
  zope.formlib.interfaces.InvalidCSRFTokenError: Invalid CSRF token

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
    pass


class Display(grok.DisplayForm):
    pass


class EditProtected(grok.EditForm):
    method = 'POST'  # only allow submits over POST requests.


class EditCsrfProtected(EditProtected):
    protected = True  # enables CSRF protection.
