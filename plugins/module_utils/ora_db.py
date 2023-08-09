# Copyright: (c) 2020, Ari Stark <ari.stark@netcourrier.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible.module_utils.basic import os

try:
    HAS_CX_ORACLE = True
    import oracledb as cx_Oracle
except ImportError:
    HAS_CX_ORACLE = False


class OraDB:
    """Help to manage database operations."""

    module = None
    connection_parameters = {}
    connection = None
    version = None
    cursor = None
    ddls = []

    def __init__(self, module):
        """Create an autocommit connection and a single cursor.

        module -- an intialized AnsibleModule object

        For a standard connection, module must have following parameters :
        - hostname, port and service_name to generate a DSN,
        - username and password to connect as a user,
        - mode to know if it must connect in sysdba.
        For connection with a wallet, module doesn't need username nor password.
        """
        if not HAS_CX_ORACLE:
            module.fail_json(msg='Unable to load cx_Oracle. Try `pip install cx_Oracle`')

        self.module = module
        hostname = module.params['hostname']
        mode = module.params['mode']
        oracle_home = module.params['oracle_home']
        password = module.params['password']
        port = module.params['port']
        service_name = module.params['service_name']
        username = module.params['username']

        if oracle_home:
            os.environ['ORACLE_HOME'] = oracle_home

        # Setting connection
        if username and password:
            self.connection_parameters['user'] = username
            self.connection_parameters['password'] = password
            self.connection_parameters['dsn'] = cx_Oracle.makedsn(host=hostname, port=port, service_name=service_name)
        else:  # Using Oracle wallet
            self.connection_parameters['dsn'] = service_name

        if mode == 'sysdba':
            self.connection_parameters['mode'] = cx_Oracle.SYSDBA
	elif mode == 'sysoper':
            self.connection_parameters['mode'] = cx_Oracle.SYSOPER

        # Connecting
        try:
            self.connection = cx_Oracle.connect(**self.connection_parameters)
            self.version = self.connection.version
            self.connection.autocommit = True
            self.cursor = self.connection.cursor()
        except cx_Oracle.DatabaseError as e:
            error = e.args[0]
            module.fail_json(msg=error.message, code=error.code)

    def execute_select(self, sql, params=None, fetchone=False):
        """Execute a select query and return fetched data.

        sql -- SQL query
        params -- Dictionary of bind parameters (default {})
        fetchone -- If True, fetch one row, otherwise fetch all rows (default False)
        """
        if params is None:
            params = {}
        try:
            self.cursor.execute(sql, params)
            return self.cursor.fetchone() if fetchone else self.cursor.fetchall()
        except cx_Oracle.DatabaseError as e:
            error = e.args[0]
            self.module.fail_json(msg=error.message, code=error.code, request=sql, params=params, ddls=self.ddls)

    def execute_select_to_dict(self, sql, params=None):
        """Execute a select query and return a list of dictionaries : one dictionary for each row.

        sql -- SQL query
        params -- Dictionary of bind parameters (default {})
        """
        if params is None:
            params = {}
        try:
            self.cursor.execute(sql, params)
            column_names = [description[0].lower() for description in
                            self.cursor.description]  # First element is the column name.
            return [dict(zip(column_names, row)) for row in self.cursor]
        except cx_Oracle.DatabaseError as e:
            error = e.args[0]
            self.module.fail_json(msg=error.message, code=error.code, request=sql, params=params, ddls=self.ddls)

    def execute_ddl(self, request):
        """Execute a DDL request and keep trace it in ddls attribute.

        request -- SQL query, no bind parameter allowed on DDL request.

        In check mode, query is not executed.
        """
        try:
            if not self.module.check_mode:
                self.cursor.execute(request)
                self.ddls.append(request)
            else:
                self.ddls.append('--' + request)
        except cx_Oracle.DatabaseError as e:
            error = e.args[0]
            self.module.fail_json(msg=error.message, code=error.code, request=request, ddls=self.ddls)

    def execute_statement(self, statement):
        """Execute a statement, can be a query or a procedure and return lines of dbms_output.put_line().

        statement -- SQL request or PL/SQL block

        In check mode, statement is not executed.
        If PL/SQL block contains put_line, the output will be returned.
        """
        output_lines = []
        try:
            if not self.module.check_mode:
                if 'dbms_output.put_line' in statement.lower():
                    self.cursor.callproc('dbms_output.enable', [None])
                    self.cursor.execute(statement)

                    chunk_size = 100  # Get lines by batch of 100
                    # create variables to hold the output
                    lines_var = self.cursor.arrayvar(str, chunk_size)  # out variable
                    num_lines_var = self.cursor.var(int)  # in/out variable
                    num_lines_var.setvalue(0, chunk_size)

                    # fetch the text that was added by PL/SQL
                    while True:
                        self.cursor.callproc('dbms_output.get_lines', (lines_var, num_lines_var))
                        num_lines = num_lines_var.getvalue()
                        output_lines.extend(lines_var.getvalue()[:num_lines])
                        if num_lines < chunk_size:  # if less lines than the chunk value was fetched, it's the end
                            break
                else:
                    self.cursor.execute(statement)
                self.ddls.append(statement)
            else:
                self.ddls.append('--' + statement)
            return output_lines
        except cx_Oracle.DatabaseError as e:
            error = e.args[0]
            self.module.fail_json(msg=error.message, code=error.code, request=statement)

    def try_connect(self, username, password):
        """Try to connect with a different user."""
        connection_parameters = {'user': username, 'password': password, 'dsn': self.connection_parameters['dsn']}
        # Connecting
        try:
            cx_Oracle.connect(**connection_parameters)
            return 0
        except cx_Oracle.DatabaseError as e:
            error = e.args[0]
            return error.code
