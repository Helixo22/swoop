"""GTK4 + libadwaita user interface of Swoop.

Importing this package selects the GTK and libadwaita versions for its modules.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
