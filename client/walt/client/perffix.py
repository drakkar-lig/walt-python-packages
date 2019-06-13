import locale

# importing pkg_resources is slow, and importing plumbum.cli
# causes pkg_resources to be used unless the locale starts with 'en'
saved_locale = locale.getlocale(locale.LC_CTYPE)
locale.setlocale(locale.LC_CTYPE, 'en_US.UTF-8')
import plumbum.cli

# restore locale
locale.setlocale(locale.LC_CTYPE, saved_locale)
