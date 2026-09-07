import grokcore.view as grok


class NotAnInterfaceClass:
    grok.skin('failing_directive')
