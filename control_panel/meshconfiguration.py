#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: set expandtab tabstop=4 shiftwidth=4 :

# Project Byzantium: http://wiki.hacdc.org/index.php/Byzantium
# License: GPLv3

"""Configure and manipulate mesh-enabled wireless network interfaces.

Wired interfaces (Ethernet) are reserved for use as net.gateways and fall
under a different web app.
"""

# For the time being this class is designed to operate with the Babel protocol
# (http://www.pps.jussieu.fr/~jch/software/babel/).  It would have to be
# rewritten to support a different (or more) protocols.

# TODO:
# - Make network interfaces that don't exist anymore go away.
# - Detect when an interface is already routing and instead offer the ability
#   to remove it from the mesh.  Do that in the MeshConfiguration.index()
#   method.
# - Add support for other mesh routing protocols for interoperability.  This
#   will involve the user picking the routing protocol after picking the
#   network interface.  This will also likely involve selecting multiple mesh
#   routing protocols (i.e., babel+others).

import logging
import os
import signal
import subprocess
import time

import _utils
import models.mesh
import models.state
import models.wired_network
import models.wireless_network


class MeshConfiguration(object):
    """Configure mesh networking on wireless network interfaces."""

    def __init__(self, templatelookup, test):
        self.templatelookup = templatelookup
        self.test = test

        # Class constants.
        self.babeld = '/usr/local/bin/babeld'
        self.babeld_pid = '/var/run/babeld.pid'
        self.babeld_timeout = 3

        netconfdb, meshconfdb = _utils.set_confdbs(self.test)
        self.network_state = models.state.NetworkState(netconfdb)
        self.mesh_state = models.state.MeshState(meshconfdb)

        # Class attributes which apply to a network interface.  By default they
        # are blank but will be populated from the mesh.sqlite database if the
        # user picks an interface that's already been set up.
        self.interface = ''
        self.protocol = ''
        self.enabled = ''
        self.pid = ''

    def pid_check(self):
        """Get the pid of babeld.

        Returns:
            A string with the pid if found, empty string if not.
        """
        pid = ''
        if os.path.exists(self.babeld_pid):
            logging.debug("Reading PID of babeld.")
            pidfile = open(self.babeld_pid, 'r')
            pid = pidfile.readline()
            pidfile.close()
            logging.debug("PID of babeld: %s", str(pid))
        return pid

    def index(self):
        """Method that generates /meshconfiguration page."""
        # This is technically irrelevant because the class' attributes are blank
        # when instantiated, but it's useful for setting up the HTML fields.
        self.reinitialize_attributes()

        # Populate the database of mesh interfaces using the network interface
        # database as a template.  Start by pulling a list of interfaces out of
        # the network configuration database.
        error = []
        interfaces = []
        results = self.network_state.list(
            'wireless',
            models.wireless_network.WirelessNetwork)
        active_interfaces = []
        if not results:
            # Display an error page which says that no wireless interfaces have
            # been configured yet.
            error.append("<p>ERROR: No wireless network interfaces have been "
                         "configured yet.  <a href='/network'>You need to do "
                         "that first!</a></p>")
        else:

            # Walk through the list of results.
            for i in results:
                # Is the network interface already configured?
                if i.enabled == 'yes':
                    # See if the interface is already in the mesh configuration
                    # database, and if it's not insert it.

                    interface_found = self.mesh_state.list(
                        'meshes',
                        models.mesh.Mesh,
                        {'interface': i.mesh_interface})

                    interface_tag = ("<input type='submit' name='interface' "
                                     "value='")
                    if not interface_found:
                        models.mesh.Mesh(
                            interface=i.mesh_interface,
                            protocol='babel',
                            enabled='no',
                            persistance=self.mesh_state)

                        # This is a network interface that's ready to
                        # configure, so add it to the HTML template as a
                        # button.
                        interfaces.append(
                            "%s%s' style='background-color:white;' />\n" %
                            (interface_tag, i.mesh_interface))
                    else:
                        # If the interface is enabled, add it to the row of
                        # active interfaces with a different color.
                        if interface_found[0].enabled == 'yes':
                            active_interfaces.append(
                                "%s%s' style='background-color:green;' />\n" %
                                (interface_tag, i.mesh_interface))
                        else:
                            # The mesh interface hasn't been configured.
                            interfaces.append("%s%s' />\n" %
                                              (interface_tag,
                                               i.mesh_interface))

                else:
                    # This interface isn't configured but it's in the database,
                    # so add it to the template as an unclickable button.
                    # While it might not be a good idea to put unusable buttons
                    # into the page, it would tell the user that the interfaces
                    # were detected.
                    interfaces.append(
                        "%s%s' style='background-color:orange;' />\n" %
                        (interface_tag, i.mesh_interface))

        # Render the HTML page.
        try:
            page = self.templatelookup.get_template("/mesh/index.html")
            return page.render(title = "Byzantium Node Mesh Configuration",
                               purpose_of_page = "Configure Mesh Interfaces",
                               error = ''.join(error),
                               interfaces = ''.join(interfaces),
                               active_interfaces = ''.join(active_interfaces))
        except:
            _utils.output_error_data()
    index.exposed = True

    def reinitialize_attributes(self):
        """Reset attributes to the empty string."""
        logging.debug("Reinitializing class attributes of "
                      "MeshConfiguration().")
        self.interface = ''
        self.protocol = ''
        self.enabled = ''
        self.pid = ''

    def addtomesh(self, interface=None):
        """Allows the user to add a wireless interface to the mesh.

         Assumes that the interface is already configured (we wouldn't get this
         far if it wasn't).

        Args:
            interface: str, interface to add

        Accessible at /meshconfiguration/addtomesh.
        """
        # Store the name of the network interface and whether or not it's
        # enabled in the object's attributes.  Right now only the Babel
        # protocol is supported, so that's hardcoded for the moment (but it
        # could change in later releases).
        self.interface = interface
        self.protocol = 'babel'
        self.enabled = 'no'

        # Render the HTML page.
        try:
            page = self.templatelookup.get_template("/mesh/addtomesh.html")
            return page.render(title = "Byzantium Node Mesh Configuration",
                               purpose_of_page = "Enable Mesh Interfaces",
                               interface = self.interface,
                               protocol = self.protocol)
        except:
            _utils.output_error_data()
    addtomesh.exposed = True

    def _pid_helper(self, pid, error, output, commit=False):
        """Find babeld pid and update enabled-ness.

        Args:
            pid: str, the pid being checked
            error: str, error string to add errors to
            output: str, the output strint to add to
            commit: bool, whether to commit the state change to persistant
                storage

        Returns:
            The error string and the output string
        """
        if not os.path.isdir('/proc/' + pid):
            error = ("ERROR: babeld is not running!  Did it crash during or "
                     "after startup?")
        else:
            output = ("%s has been successfully started with PID %s." %
                      (self.babeld, pid))

            # Update the mesh configuration database to take into account
            # the presence of the new interface.
            if commit:
                self.mesh_state.replace(
                    {'kind': 'meshes', 'interface': self.interface},
                    {'kind': 'meshes', 'interface': self.interface,
                     'enabled': 'yes'})
        return error, output

    def update_babeld(self, common_babeld_opts, unique_babeld_opts,
                      interfaces):
        """Assemble the invocation of babeld.

        Args:
            common_babeld_opts: list, list of common command line flags for
                babeld
            unique_babeld_opts: list, list of unique command line flags for
                babeld
            interfaces: list, list of interfaces

        Returns:
            A list with the complete command line to run
        """
        babeld_command = []
        babeld_command.append(self.babeld)
        babeld_command = babeld_command + common_babeld_opts
        babeld_command = babeld_command + unique_babeld_opts + interfaces
        logging.debug("babeld command to be executed: %s",
                      ' '.join(babeld_command))

        # Test to see if babeld is running.  If it is, it's routing for at
        # least one interface, in which case we add the one the user just
        # picked to the list because we'll have to restart babeld.  Otherwise,
        # we just start babeld.
        pid = self.pid_check()
        if pid:
            if self.test:
                logging.debug("Pretending to kill babeld.")
            else:
                logging.debug("Killing babeld...")
                os.kill(int(pid), signal.SIGTERM)
            time.sleep(self.babeld_timeout)
        if self.test:
            logging.debug("Pretending to restart babeld.")
        else:
            logging.debug("Restarting babeld.")
            subprocess.Popen(babeld_command)
        time.sleep(self.babeld_timeout)
        return babeld_command

    def enable(self):
        """Runs babeld to turn self.interface into a mesh interface.

        Available at /meshconfiguration/enable
        """
        # Set up the error and successful output messages.
        error = ''
        output = ''

        # Set up a default set of command line options for babeld.  Some of
        # these are redundant but are present in case an older version of
        # babeld is used on the node.  See the following file to see why:
        # http://www.pps.jussieu.fr/~jch/software/babel/CHANGES.text
        common_babeld_opts = ['-m', 'ff02:0:0:0:0:0:1:6', '-p', '6696', '-D',
                              '-g', '33123', '-c', '/etc/babeld.conf']

        # Create a set of unique command line options for babeld.  Right now,
        # this variable is empty but it might be used in the future.  Maybe
        # it'll be populated from a config file or something.
        unique_babeld_opts = []

        # Set up a list of mesh interfaces for which babeld is already running.
        results = self.mesh_state.list(
            'meshes',
            models.mesh.Mesh,
            {'enabled': 'yes', 'protocol': 'babel'})
        interfaces = []
        for i in results:
            logging.debug("Adding interface: %s", i.interface)
            interfaces.append(i.interface)

        # By definition, if we're in this method the new interface hasn't been
        # added yet.
        interfaces.append(self.interface)

        self.update_babeld(common_babeld_opts, unique_babeld_opts, interfaces)

        # Get the PID of babeld, then test to see if that pid exists and
        # corresponds to a running babeld process.  If there is no match,
        # babeld isn't running.
        pid = self.pid_check()
        if pid:
            error, output = self._pid_helper(pid, error, output, commit=True)

        # Render the HTML page.
        try:
            page = self.templatelookup.get_template("/mesh/enabled.html")
            return page.render(title = "Byzantium Node Mesh Configuration",
                               purpose_of_page = "Mesh Interface Enabled",
                               protocol = self.protocol,
                               interface = self.interface,
                               error = error, output = output)
        except:
            _utils.output_error_data()
    enable.exposed = True

    def removefrommesh(self, interface=None):
        """Allows the user to remove a configured interface from the mesh.

        Available at /meshconfiguration/removefrommesh

        Args:
            interface: str, the interface to remove
        """
        logging.debug("Entered MeshConfiguration.removefrommesh().")

        # Configure this instance of the object for the interface the user
        # wants to remove from the mesh.
        self.interface = interface
        self.protocol = 'babel'
        self.enabled = 'yes'

        # Render the HTML page.
        try:
            page = self.templatelookup.get_template(
                "/mesh/removefrommesh.html")
            return page.render(title = "Byzantium Node Mesh Configuration",
                               purpose_of_page = "Disable Mesh Interface",
                               interface = interface)
        except:
            _utils.output_error_data()
    removefrommesh.exposed = True

    def disable(self):
        """Re-runs babeld without self.interface to drop it out of the mesh.

        Available at /meshconfiguration/disable
        """
        logging.debug("Entered MeshConfiguration.disable().")

        # Set up the error and successful output messages.
        error = ''
        output = ''

        # Set up a default set of command line options for babeld.  Some of
        # these are redundant but are present in case an older version of
        # babeld is used on the node.  See the following file to see why:
        # http://www.pps.jussieu.fr/~jch/software/babel/CHANGES.text
        common_babeld_opts = ['-m', 'ff02:0:0:0:0:0:1:6', '-p', '6696', '-D',
                              '-g', '33123', '-c', '/etc/babeld.conf']

        # Create a set of unique command line options for babeld.  Right now,
        # this variable is empty but it might be used in the future.  Maybe
        # it'll be populated from a config file or something.
        unique_babeld_opts = []

        # Set up a list of mesh interfaces for which babeld is already running
        # but omit self.interface.
        results = self.mesh_state.list(
            'meshes',
            models.mesh.Mesh,
            {'enabled': 'yes', 'protocol': 'babel'})
        interfaces = []
        for i in results:
            if i.interface != self.interface:
                interfaces.append(i.interface)

        # If there are no mesh interfaces configured anymore, then the node
        # is offline.
        if not interfaces:
            output = 'Byzantium node offline.'

        babeld_command = self.update_babeld(common_babeld_opts,
                                            unique_babeld_opts,
                                            interfaces)

        # If there is at least one wireless network interface still configured,
        # then re-run babeld.
        if interfaces:
            logging.debug("value of babeld_command is %s", babeld_command)
            if self.test:
                logging.debug("Pretending to restart babeld.")
            else:
                subprocess.Popen(babeld_command)
            time.sleep(self.babeld_timeout)

        # Get the PID of babeld, then test to see if that pid exists and
        # corresponds to a running babeld process.  If there is no match,
        # babeld isn't running, in which case something went wrong.
        pid = self.pid_check()
        if pid:
            error, output = self._pid_helper(pid, error, output)
        else:
            # There are no mesh interfaces left, so update the database to
            # deconfigure self.interface.
            self.mesh_state.replace(
                {'kind': 'meshes', 'interface': self.interface},
                {'kind': 'meshes', 'interface': self.interface,
                 'enabled': 'no'})

        # Render the HTML page.
        try:
            page = self.templatelookup.get_template("/mesh/disabled.html")
            return page.render(title = "Byzantium Node Mesh Configuration",
                               purpose_of_page = "Disable Mesh Interface",
                               error = error, output = output)
        except:
            _utils.output_error_data()
    disable.exposed = True
