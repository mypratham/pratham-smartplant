Debug console
=============

The debug console lets you have a Python prompt with the full Zope
environment loaded (which includes the ZCML configuration, as well as an open
database connection).

Let's define a helper to run the debug script and trap SystemExit exceptions
that would otherwise hide the output

    >>> from __future__ import print_function
    >>> import sys
    >>> from zope.app.appsetup import debug
    >>> def run(*args):
    ...     sys.argv[0] = 'debug'
    ...     sys.stderr = sys.stdout
    ...     try:
    ...         debug.main(args)
    ...     except SystemExit as e:
    ...         print("(exited with status %d)" % e.code)

If you call the script with no arguments, it displays a brief error message
on stderr

    >>> run()
    Error: please specify a configuration file
    For help, use debug -h
    (exited with status 2)

We need to pass a ZConfig configuration file as an argument

    >>> run('-C', 'test.conf.txt')
    The application root is known as `root`.

Now you have the root object from the open database available as a global
variable named 'root' in the __main__ module:

    >>> main_module = sys.modules['__main__']
    >>> main_module.root            # doctest: +ELLIPSIS
    <zope.site.folder.Folder object at ...>

and we have asked Python to enter interactive mode by setting the
PYTHONINSPECT environment variable

    >>> import os
    >>> os.environ.get('PYTHONINSPECT')
    'true'

We have to do extra work to honor the PYTHONSTARTUP environment variable:

    >>> pythonstartup = os.path.join(os.path.dirname(debug.__file__),
    ...                              'testdata', 'pythonstartup.py')
    >>> os.environ['PYTHONSTARTUP'] = pythonstartup
    >>> run('-C', 'test.conf.txt')
    The application root is known as `root`.

You can see that our pythonstartup file was executed because it changed
the prompt

    >>> sys.ps1
    'debug> '

