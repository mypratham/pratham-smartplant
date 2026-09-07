"""
Forms cannot define a render method. Here we show the case where the
EditForm has no explicit template associated with it:

  >>> grok.testing.grok(__name__)
  Traceback (most recent call last):
  ...
  martian.error.GrokError: It is not allowed to specify a custom 'render' \
  method for form <class 'grokcore.formlib.tests.base.form.norender2.Edit'>. \
  Forms either use the default template or a custom-supplied one.

"""

import grokcore.formlib as grok


class Mammoth(grok.Context):
    pass


class Edit(grok.EditForm):
    # not allowed to have a render method
    def render(self):
        return "this cannot be"
