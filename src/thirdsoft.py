#!/usr/bin/python
# coding: utf-8

# Ubuntu Tweak - PyGTK based desktop configure tool
#
# Copyright (C) 2007-2008 TualatriX <tualatrix@gmail.com>
#
# Ubuntu Tweak is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Ubuntu Tweak is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ubuntu Tweak; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA

import os
import gtk
import time
import thread
import subprocess
import pango
import gobject
import apt_pkg
import webbrowser
import urllib

from common.config import Config, TweakSettings
from common.consts import *
from common.sourcedata import SOURCES_LIST, SOURCES_DATA, SOURCES_DEPENDENCIES, SOURCES_CONFLICTS
from common.appdata import APP_DICT, APPS
from common.appdata import get_app_logo, get_app_describ
from common.appdata import get_source_logo, get_source_describ
from common.policykit import PolkitButton, DbusProxy
from common.widgets import ListPack, TweakPage, GconfCheckButton
from common.widgets.dialogs import *
from common.factory import WidgetFactory
from common.package import package_worker, PackageInfo
from common.notify import notify
from common.misc import URLLister
from installer import AppView
from backends.packageconfig import PATH
from aptsources.sourceslist import SourceEntry, SourcesList

config = Config()
ppas = []

BUILTIN_APPS = APP_DICT.keys()
BUILTIN_APPS.extend(APPS.keys())

(
    COLUMN_ENABLED,
    COLUMN_URL,
    COLUMN_DISTRO,
    COLUMN_COMPS,
    COLUMN_PACKAGE,
    COLUMN_LOGO,
    COLUMN_NAME,
    COLUMN_COMMENT,
    COLUMN_DISPLAY,
    COLUMN_HOME,
    COLUMN_KEY,
) = range(11)

(
    ENTRY_URL,
    ENTRY_DISTRO,
    ENTRY_COMPS,
) = range(3)

(
    SOURCE_NAME,
    SOURCE_PACKAGE,
    SOURCE_HOME,
    SOURCE_KEY,
) = range(4)

def refresh_source(parent):
    dialog = UpdateCacheDialog(parent)
    res = dialog.run()

    proxy.set_list_state('normal')

    new_pkg = []
    for pkg in package_worker.get_new_package():
        if pkg in BUILTIN_APPS:
            new_pkg.append(pkg)

    new_updates = list(package_worker.get_update_package())

    if new_pkg or new_updates:
        updateview = UpdateView()
        updateview.set_headers_visible(False)

        if new_pkg:
            updateview.update_model(new_pkg)

        if new_updates:
            updateview.update_updates(package_worker.get_update_package())

        dialog = QuestionDialog(_('You can install the new applications by selecting them and choose "Yes".\nOr you can install them at Add/Remove by choose "No".'),
            title = _('New applications are available to update'))

        vbox = dialog.vbox
        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.set_size_request(-1, 200)
        vbox.pack_start(sw, False, False, 0)
        sw.add(updateview)
        sw.show_all()

        res = dialog.run()
        dialog.destroy()

        if res == gtk.RESPONSE_YES:
            to_rm = updateview.to_rm
            to_add = updateview.to_add
            package_worker.perform_action(parent, to_add, to_rm)

            package_worker.update_apt_cache(True)

            done = package_worker.get_install_status(to_add, to_rm)

            if done:
                InfoDialog(_('Update Successful!')).launch()
            else:
                ErrorDialog(_('Update Failed!')).launch()

        return True
    else:
        dialog = InfoDialog(_("Your system is clean and there's no update yet."),
            title = _('The software information is up-to-date now'))

        dialog.launch()
        return False

class UpdateView(AppView):
    def __init__(self):
        AppView.__init__(self)

    def update_model(self, apps, cates=None):
        model = self.get_model()

        model.append((None,
                        None,
                        None,
                        None,
                        None,
                        '<span size="large" weight="bold">%s</span>' % _('Available New Applications'),
                        None,
                        None))

        super(UpdateView, self).update_model(apps, cates)

    def update_updates(self, pkgs):
        '''apps is a list to iter pkgname,
        cates is a dict to find what the category the pkg is
        '''
        model = self.get_model()

        model.append((None,
                        None,
                        None,
                        None,
                        None,
                        '<span size="large" weight="bold">%s</span>' % _('Available Package Updates'),
                        None,
                        None))

        apps = []
        updates = []
        for pkg in pkgs:
            if pkg in BUILTIN_APPS:
                apps.append(pkg)
            else:
                updates.append(pkg)

        for pkgname in apps:
            pixbuf = get_app_logo(pkgname)

            package = PackageInfo(pkgname)
            appname = package.get_name()
            desc = get_app_describ(pkgname)

            self.append_app(True,
                    pixbuf,
                    pkgname,
                    appname,
                    desc,
                    0,
                    'update')
            self.to_add.append(pkgname)

        for pkgname in updates:
            package = package_worker.get_cache()[pkgname]

            self.append_update(True, package.name, package.summary)

class UpdateCacheDialog:
    """This class is modified from Software-Properties"""
    def __init__(self, parent):
        self.parent = parent

        self.dialog = QuestionDialog(_('To install software and updates from '
            'newly added or changed sources, you have to reload the information '
            'about available software.\n\n'
            'You need a working internet connection to continue.'), 
            title=_('The information about available software is out-of-date'))

    def update_cache(self, window_id, lock):
        """start synaptic to update the package cache"""
        try:
            apt_pkg.PkgSystemUnLock()
        except SystemError:
            pass
        cmd = []
        if os.getuid() != 0:
            cmd = ['/usr/bin/gksu',
                   '--desktop', '/usr/share/applications/synaptic.desktop',
                   '--']
        
        cmd += ['/usr/sbin/synaptic', '--hide-main-window',
               '--non-interactive',
               '--parent-window-id', '%s' % (window_id),
               '--update-at-startup']
        subprocess.call(cmd)
        lock.release()

    def run(self):
        """run the dialog, and if reload was pressed run synaptic"""
        res = self.dialog.run()
        self.dialog.hide()
        if res == gtk.RESPONSE_YES:
            self.parent.set_sensitive(False)
            self.parent.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
            lock = thread.allocate_lock()
            lock.acquire()
            t = thread.start_new_thread(self.update_cache,
                                       (self.parent.window.xid, lock))
            while lock.locked():
                while gtk.events_pending():
                    gtk.main_iteration()
                    time.sleep(0.05)
            self.parent.set_sensitive(True)
            self.parent.window.set_cursor(None)
        return res

class SourcesView(gtk.TreeView):
    __gsignals__ = {
        'sourcechanged': (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE, ())
    }
    def __init__(self):
        gtk.TreeView.__init__(self)

        self.model = self.__create_model()
        self.set_model(self.model)
        self.model.set_sort_column_id(COLUMN_NAME, gtk.SORT_ASCENDING)
        self.__add_column()

        self.update_model()
        self.selection = self.get_selection()

    def get_sourceslist(self):
        from aptsources.sourceslist import SourcesList
        return SourcesList()

    def __create_model(self):
        model = gtk.ListStore(
                gobject.TYPE_BOOLEAN,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING,
                gtk.gdk.Pixbuf,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING,
                gobject.TYPE_STRING)

        return model

    def __add_column(self):
        renderer = gtk.CellRendererToggle()
        renderer.connect('toggled', self.on_enable_toggled)
        column = gtk.TreeViewColumn(' ', renderer, active = COLUMN_ENABLED)
        column.set_sort_column_id(COLUMN_ENABLED)
        self.append_column(column)

        column = gtk.TreeViewColumn(_('Third-Party Sources'))
        column.set_sort_column_id(COLUMN_NAME)
        column.set_spacing(5)
        renderer = gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.set_attributes(renderer, pixbuf = COLUMN_LOGO)

        renderer = gtk.CellRendererText()
        renderer.set_property('ellipsize', pango.ELLIPSIZE_END)
        column.pack_start(renderer, True)
        column.set_attributes(renderer, markup = COLUMN_DISPLAY)

        self.append_column(column)

    def update_model(self):
        self.model.clear()
        sourceslist = self.get_sourceslist()

        for entry in SOURCES_DATA:
            enabled = False
            url = entry[ENTRY_URL]
            comps = entry[ENTRY_COMPS]
            distro = entry[ENTRY_DISTRO]

            source = entry[-1]
            name = source[SOURCE_NAME]
            package = source[SOURCE_PACKAGE]
            comment = get_source_describ(package)
            logo = get_source_logo(package)
            home = source[SOURCE_HOME]
            if home:
                home = 'http://' + home
            key = source[SOURCE_KEY]
            if key:
                key = os.path.join(DATA_DIR, 'aptkeys', source[SOURCE_KEY])

            for source in sourceslist:
                if url in source.str() and source.type == 'deb':
                    enabled = not source.disabled

            iter = self.model.append()

            self.model.set(iter,
                    COLUMN_ENABLED, enabled,
                    COLUMN_URL, url,
                    COLUMN_DISTRO, distro,
                    COLUMN_COMPS, comps,
                    COLUMN_COMMENT, comment,
                    COLUMN_PACKAGE, package,
                    COLUMN_NAME, name,
                    COLUMN_DISPLAY, '<b>%s</b>\n%s' % (name, comment),
                    COLUMN_LOGO, logo,
                    COLUMN_HOME, home,
                    COLUMN_KEY, key,
                )

    def setup_ubuntu_cn_mirror(self):
        global SOURCES_DATA
        iter = self.model.get_iter_first()
        sourceslist = self.get_sourceslist()

        SOURCES_DATA = self.__filter_source_to_mirror()

        window = self.get_toplevel().window
        if window:
            window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        while iter:
            while gtk.events_pending():
                gtk.main_iteration()
            url  = self.model.get_value(iter, COLUMN_URL)
            name = self.model.get_value(iter, COLUMN_NAME)
            enable = self.model.get_value(iter, COLUMN_ENABLED)

            if self.has_mirror_ppa(url):
                if enable:
                    self.set_source_disable(name)

                url = url.replace('ppa.launchpad.net', 'archive.ubuntu.org.cn/ubuntu-cn')
                self.model.set_value(iter, COLUMN_URL, url)

                if enable:
                    self.set_source_enabled(name)

            iter = self.model.iter_next(iter)

        if window:
            window.set_cursor(None)

    def __filter_source_to_mirror(self):
        newsource = []
        for item in SOURCES_DATA:
            url = item[0]
            if self.has_mirror_ppa(url):
                url = url.replace('ppa.launchpad.net', 'archive.ubuntu.org.cn/ubuntu-cn')
                newsource.append([url, item[1], item[2], item[3]])
        else:
            newsource.append(item)

        return newsource

    def has_mirror_ppa(self, url):
        return 'ppa.launchpad.net' in url and url.split('/')[3] in ppas

    def get_sourcelist_status(self, url):
        for source in self.get_sourceslist():
            if url in source.str() and source.type == 'deb':
                return not source.disabled
        return False

    def on_enable_toggled(self, cell, path):
        iter = self.model.get_iter((int(path),))

        name = self.model.get_value(iter, COLUMN_NAME)
        enabled = self.model.get_value(iter, COLUMN_ENABLED)

        if enabled is False and name in SOURCES_DEPENDENCIES:
            #FIXME: If more than one dependency
            dependency = SOURCES_DEPENDENCIES[name]
            if self.get_source_enabled(dependency) is False:
                dialog = QuestionDialog(\
                            _('To enable this Source, You need to enable "%s" at first.\nDo you wish to continue?') \
                            % dependency,
                            title=_('Dependency Notice'))
                if dialog.run() == gtk.RESPONSE_YES:
                    self.set_source_enabled(dependency)
                    self.set_source_enabled(name)
                else:
                    self.model.set(iter, COLUMN_ENABLED, enabled)

                dialog.destroy()
            else:
                self.do_source_enable(iter, not enabled)
        elif enabled and name in SOURCES_DEPENDENCIES.values():
            HAVE_REVERSE_DEPENDENCY = False
            for k, v in SOURCES_DEPENDENCIES.items():
                if v == name and self.get_source_enabled(k):
                    ErrorDialog(_('You can\'t disable this Source because "%(SOURCE)s" depends on it.\nTo continue you need to disable "%(SOURCE)s" first.') % {'SOURCE': k}).launch()
                    HAVE_REVERSE_DEPENDENCY = True
                    break
            if HAVE_REVERSE_DEPENDENCY:
                self.model.set(iter, COLUMN_ENABLED, enabled)
            else:
                self.do_source_enable(iter, not enabled)
        elif not enabled and name in SOURCES_CONFLICTS.values() or name in SOURCES_CONFLICTS.keys():
            key = None
            if name in SOURCES_CONFLICTS.keys():
                key = SOURCES_CONFLICTS[name]
            if name in SOURCES_CONFLICTS.values():
                for k, v in SOURCES_CONFLICTS.items():
                    if v == name:
                        key = k
            if self.get_source_enabled(key):
                ErrorDialog(_('You can\'t enable this Source because "%(SOURCE)s" conflicts with it.\nTo continue you need to disable "%(SOURCE)s" first.') % {'SOURCE': key}).launch()
                self.model.set(iter, COLUMN_ENABLED, enabled)
            else:
                self.do_source_enable(iter, not enabled)
        else:
            self.do_source_enable(iter, not enabled)

    def on_source_foreach(self, model, path, iter, name):
        m_name = model.get_value(iter, COLUMN_NAME)
        if m_name == name:
            if self._foreach_mode == 'get':
                self._foreach_take = model.get_value(iter, COLUMN_ENABLED)
            elif self._foreach_mode == 'set':
                self._foreach_take = iter

    def get_source_enabled(self, name):
        '''
        Search source by name, then get status from model
        '''
        self._foreach_mode = 'get'
        self._foreach_take = None
        self.model.foreach(self.on_source_foreach, name)
        return self._foreach_take

    def set_source_enabled(self, name):
        '''
        Search source by name, then call do_source_enable
        '''
        self._foreach_mode = 'set'
        self._foreach_status = None
        self.model.foreach(self.on_source_foreach, name)
        self.do_source_enable(self._foreach_take, True)

    def set_source_disable(self, name):
        '''
        Search source by name, then call do_source_enable
        '''
        self._foreach_mode = 'set'
        self._foreach_status = None
        self.model.foreach(self.on_source_foreach, name)
        self.do_source_enable(self._foreach_take, False)

    def do_source_enable(self, iter, enable):
        '''
        Do the really source enable or disable action by iter
        Only emmit signal when source is changed
        '''

        url = self.model.get_value(iter, COLUMN_URL)

        icon = self.model.get_value(iter, COLUMN_LOGO)
        distro = self.model.get_value(iter, COLUMN_DISTRO)
        comment = self.model.get_value(iter, COLUMN_NAME)
        package = self.model.get_value(iter, COLUMN_PACKAGE)
        comps = self.model.get_value(iter, COLUMN_COMPS)
        key = self.model.get_value(iter, COLUMN_KEY)

        pre_status = self.get_sourcelist_status(url)

        if key:
            proxy.add_apt_key(key)

        if not comps:
            distro = distro + '/'

        if TweakSettings.get_separated_sources():
            result = proxy.set_separated_entry(url, distro, comps, comment, enable, package)
        else:
            result = proxy.set_entry(url, distro, comps, comment, enable)

        if str(result) == 'enabled':
            self.model.set(iter, COLUMN_ENABLED, True)
        else:
            self.model.set(iter, COLUMN_ENABLED, False)

        if pre_status != enable:
            self.emit('sourcechanged')

        if enable:
            notify.update(_('New source has been enabled'), _('%s is enabled now, Please click the refresh button to update the application cache.') % comment)
            notify.set_icon_from_pixbuf(icon)
            notify.show()

class SourceDetail(gtk.VBox):
    def __init__(self):
        gtk.VBox.__init__(self)

        self.table = gtk.Table(2, 2)
        self.pack_start(self.table)

        gtk.link_button_set_uri_hook(self.click_website)

        items = [_('Homepage'), _('Source URL'), _('Description')]
        for i, text in enumerate(items):
            label = gtk.Label()
            label.set_markup('<b>%s</b>' % text)

            self.table.attach(label, 0, 1, i, i + 1, xoptions = gtk.FILL, xpadding = 10, ypadding = 5)

        self.homepage_button = gtk.LinkButton('http://ubuntu-tweak.com')
        self.table.attach(self.homepage_button, 1, 2, 0, 1)
        self.url_button = gtk.LinkButton('http://ubuntu-tweak.com')
        self.table.attach(self.url_button, 1, 2, 1, 2)
        self.description = gtk.Label(_('Description is here'))
        self.description.set_line_wrap(True)
        self.table.attach(self.description, 1, 2, 2, 3)

    def click_website(self, widget, link):
        webbrowser.open(link)

    def set_details(self, homepage = None, url = None, description = None):
        if homepage:
            self.homepage_button.destroy()
            self.homepage_button = gtk.LinkButton(homepage, homepage)
            self.homepage_button.show()
            self.table.attach(self.homepage_button, 1, 2, 0, 1)

        if url:
            if 'ppa.launchpad.net' in url:
                url_section = url.split('/')
                url = 'https://launchpad.net/~%s/+archive/%s' % (url_section[3], url_section[4]) 
            self.url_button.destroy()
            self.url_button = gtk.LinkButton(url, url)
            self.url_button.show()
            self.table.attach(self.url_button, 1, 2, 1, 2)

        if description:
            self.description.set_text(description)

class ThirdSoft(TweakPage):
    def __init__(self):
        TweakPage.__init__(self, 
                _('Third-Party Software Sources'), 
                _('After every release of Ubuntu there comes a feature freeze.\nThis means only applications with bug-fixes get into the repository.\nBy using third-party DEB repositories, you can always keep up-to-date with the latest version.\nAfter adding these repositories, locate and install them using Add/Remove.'))

        sw = gtk.ScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        self.pack_start(sw)

        self.treeview = SourcesView()
        self.treeview.connect('sourcechanged', self.colleague_changed)
        self.treeview.selection.connect('changed', self.on_selection_changed)
        self.treeview.set_sensitive(False)
        self.treeview.set_rules_hint(True)
        sw.add(self.treeview)

        self.expander = gtk.Expander(_('Details'))
        self.pack_start(self.expander, False, False, 0)
        self.sourcedetail = SourceDetail()
        self.expander.set_sensitive(False)
        self.expander.add(self.sourcedetail)

        hbox = gtk.HBox(False, 5)
        self.pack_end(hbox, False, False, 0)

        un_lock = PolkitButton()
        un_lock.connect('changed', self.on_polkit_action)
        hbox.pack_end(un_lock, False, False, 0)

        self.refresh_button = gtk.Button(stock = gtk.STOCK_REFRESH)
        self.refresh_button.set_sensitive(False)
        self.refresh_button.connect('clicked', self.on_refresh_button_clicked)
        hbox.pack_end(self.refresh_button, False, False, 0)

        #FIXME close it when 0.5.0
        gobject.idle_add(self.check_ppa_entry)

        if os.getenv('LANG').startswith('zh_CN') and TweakSettings.get_use_mirror_ppa():
            thread.start_new_thread(self.start_check_cn_ppa, ())

        config.get_client().notify_add('/apps/ubuntu-tweak/use_mirror_ppa', self.value_changed)

    def value_changed(self, client, id, entry, data):
        #FIXME Back to normal source data
        self.start_check_cn_ppa()

    def start_check_cn_ppa(self):
        url = urllib.urlopen('http://archive.ubuntu.org.cn/ubuntu-cn/')

        parse = URLLister(ppas)
        data = url.read()
        parse.feed(data)

        self.treeview.setup_ubuntu_cn_mirror()

    def check_ppa_entry(self):
        if self.do_check_ppa_entry():
            dialog = QuestionDialog(_('Some of your PPA Sources need to be updated.\nDo you wish to continue?'), title=_('PPA Sources has expired'))
            UPDATE = False
            if dialog.run() == gtk.RESPONSE_YES:
                UPDATE = True
            dialog.destroy()

            if UPDATE:
                self.do_update_ppa_entry()

    def do_check_ppa_entry(self):
        content = open(SOURCES_LIST).read()
        for line in content.split('\n'):
            if self.__is_expire_ppa(line):
                return True
        return False

    def __is_expire_ppa(self, line):
        '''http://ppa.launchpad.net/tualatrix/ppa/ubuntu is the new style
        http://ppa.launchpad.net/tualatrix/ubuntu is the old style
        length check is important
        '''
        try:
            url = line.split()[1]
            if url.startswith('http://ppa.launchpad.net') and \
                    len(url.split('/')) == 5 and \
                    'ppa/ubuntu' not in line:
                return True
        except:
            pass

    def do_update_ppa_entry(self):
        content = open(SOURCES_LIST).read()
        lines = []
        for line in content.split('\n'):
            if self.__is_expire_ppa(line):
                lines.append(line.replace('/ubuntu ', '/ppa/ubuntu '))
            else:
                lines.append(line)

        if proxy.edit_file(SOURCES_LIST, '\n'.join(lines)) == 'error':
            ErrorDialog(_('Please check the permission of the sources.list file'),
                    title=_('Save failed!')).launch()
        else:
            InfoDialog(_('Update Successful!')).launch()

        self.update_thirdparty()

    def update_thirdparty(self):
        self.treeview.update_model()

    def on_selection_changed(self, widget):
        model, iter = widget.get_selected()
        if iter is None:
            return
        home = model.get_value(iter, COLUMN_HOME)
        url = model.get_value(iter, COLUMN_URL)
        description = model.get_value(iter, COLUMN_COMMENT)

        self.sourcedetail.set_details(home, url, description)

    def on_polkit_action(self, widget, action):
        global proxy
        if action:
            self.refresh_button.set_sensitive(True)

            proxy = DbusProxy(PATH)
            if proxy.get_object():
                self.treeview.set_sensitive(True)
                self.expander.set_sensitive(True)
                WARNING_KEY = '/apps/ubuntu-tweak/disable_thidparty_warning'

                if not config.get_value(WARNING_KEY):
                    dialog = WarningDialog(_('It is a possible security risk to '
                        'use packages from Third-Party Sources.\n'
                        'Please be careful and use only sources you trust.'),
                        buttons = gtk.BUTTONS_OK, title = _('Warning'))
                    checkbutton = GconfCheckButton(_('Never show this dialog'), WARNING_KEY)
                    dialog.add_option(checkbutton)

                    dialog.run()
                    dialog.destroy()
            else:
                ServerErrorDialog().launch()
        else:
            AuthenticateFailDialog().launch()

    def colleague_changed(self, widget):
        self.emit('update', 'sourceeditor', 'update_source_combo')
    
    def on_refresh_button_clicked(self, widget):
        if refresh_source(widget.get_toplevel()):
            self.emit('update', 'installer', 'normal_update')

if __name__ == '__main__':
    from utility import Test
    Test(ThirdSoft)
