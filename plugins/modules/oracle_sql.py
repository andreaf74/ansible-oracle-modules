#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2014 Mikael Sandström <oravirt@gmail.com>
# Copyright: (c) 2020, Ari Stark <ari.stark@netcourrier.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = '''
---
module: oracle_sql
short_description: Execute arbitrary sql
description:
    - This module can be used to execute arbitrary SQL queries or PL/SQL blocks against an Oracle database.
    - If the SQL query is a select statement, the result will be returned.
    - If the script contains dbms_output.put_line(), the output will be returned.
    - Connection is set to autocommit. There is no rollback mechanism implemented.
version_added: "0.8.0"
author:
    - Mikael Sandström (@oravirt)
    - Ari Stark (@ari-stark)
options:
    hostname:
        description:
            - Specify the host name or IP address of the database server computer.
        default: localhost
        type: str
    mode:
        description:
            - This option is the database administration privileges.
        default: normal
        type: str
        choices: ['normal', 'sysdba','sysoper']
    oracle_home:
        description:
            - Define the directory into which all Oracle software is installed.
            - Define ORACLE_HOME environment variable if set.
        type: str
    password:
        description:
            - Set the password to use to connect the database server.
            - Must not be set if using Oracle wallet.
        type: str
    port:
        description:
            - Specify the listening port on the database server.
        default: 1521
        type: int
    script:
        description:
            - The SQL script to execute. It can be direct SQL statements, PL/SQL blocks or the name of a file.
            - If I(script) is SQL statements, each statements must end with a semicolon at end of line.
            - If I(script) is PL/SQL blocks, each block must end with a slash on a new line.
            - If I(script) is a file, it must start with a @ (i.e @/path/to/file.sql).
        type: str
    service_name:
        description:
            - Specify the service name of the database you want to access.
        required: true
        type: str
    sql:
        description:
            - A single SQL statement.
            - If this statement is a select query (starts with select) the result is returned.
            - The statement mustn't end with a semicolon.
        type: str
    username:
        description:
            - Set the login to use to connect the database server.
            - Must not be set if using Oracle wallet.
        type: str
        aliases:
            - user
requirements:
    - Python module cx_Oracle
    - Oracle basic tools.
notes:
    - Check mode is supported.
    - In check mode, the select query are executed.
    - Diff mode is not supported.
'''

EXAMPLES = '''
# Execute one arbitrary SQL statement (no trailing semicolon)
- oracle_sql:
    hostname: "foo.server.net"
    username: "foo"
    password: "bar"
    service_name: "pdb001"
    sql: "select username from dba_users"

# Execute several arbitrary SQL statements (each statement must end with a semicolon at end of line)
- oracle_sql:
    hostname: "foo.server.net"
    username: "foo"
    password: "bar"
    service_name: "pdb001"
    script: |
        insert into foo (f1, f2) values ('ab', 'cd');
        update foo set f2 = 'fg' where f1 = 'ab';

# Execute several arbitrary PL/SQL blocks (must end with a trailing slash)
- oracle_sql:
    hostname: "foo.server.net"
    username: "foo"
    password: "bar"
    service_name: "pdb001"
    script: |
        begin
            [...]
        end;
        /
        begin
            [...]
        end;
        /

# Execute arbitrary SQL file
- oracle_sql:
    hostname: "foo.server.net"
    username: "foo"
    password: "bar"
    service_name: "pdb001"
    script: '@/u01/scripts/create-all-the-procedures.sql'
'''

RETURN = '''
data:
    description: Contains a two dimensionnal array containing the fetched lines and columns of the select query.
    returned: if I(sql) is a select statement
    type: list
    elements: list
output_lines:
    description: Contains the output of scripts made by dbms_output.put_line().
    returned: always, but is empty if I(script) doesn't contain dbms_output.put_line().
    type: list
    elements: str
statements:
    description: Contains a list of SQL statements executed.
    returned: if I(sql) is not a select statement or I(script) is used
    type: list
    elements: str
'''

import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.ari_stark.ansible_oracle_modules.plugins.module_utils.ora_db import OraDB

output_lines = []


def execute_statements(script):
    """Execute several statements.

    This function determines if it's dealing with PL/SQL blocks or multi-statement queries. It cannot deal with both.
    PL/SQL blocks is defined by a trailing slash (/).
    If there is no trailing slash, it's considered multi-statement queries separated by a semicolon.
    """
    global output_lines

    if re.search(r'/\s*$', script):  # If it's PL/SQL blocks
        seperator = r'^\s*/\s*$'
    else:  # If it's SQL statements
        seperator = r';\s*$'

    for query in re.split(seperator, script, flags=re.MULTILINE):
        if query.strip():
            output_lines += ora_db.execute_statement(query.strip())


def main():
    global module
    global ora_db

    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str', default='localhost'),
            mode=dict(type='str', default='normal', choices=['normal', 'sysdba','sysoper']),
            oracle_home=dict(type='str', required=False),
            password=dict(type='str', required=False, no_log=True),
            port=dict(type='int', default=1521),
            script=dict(type='str', required=False),
            service_name=dict(type='str', required=True),
            sql=dict(type='str', required=False),
            username=dict(type='str', required=False, aliases=['user']),
        ),
        mutually_exclusive=[['sql', 'script']],
        required_together=[['username', 'password']],
        supports_check_mode=True,
    )

    script = module.params['script']
    sql = module.params['sql']

    ora_db = OraDB(module)

    if sql:  # Mono statement.
        if re.match(r'^\s*select\s+', sql, re.IGNORECASE):
            result = ora_db.execute_select(sql)
            module.exit_json(msg='Select statement executed.', changed=False, data=result)
        else:
            ora_db.execute_statement(sql)
            module.exit_json(msg='DML or DDL statement executed.', changed=True, statements=ora_db.ddls)
    elif not script.startswith('@'):  # Multi statement
        execute_statements(script)
        module.exit_json(msg='DML or DDL statements executed.', changed=True, statements=ora_db.ddls,
                         output_lines=output_lines)
    else:  # SQL file
        try:
            file_name = script.lstrip('@')
            with open(file_name, 'r') as f:
                execute_statements(f.read())
            module.exit_json(msg='DML or DDL statements executed.', changed=True, statements=ora_db.ddls,
                             output_lines=output_lines)
        except IOError as e:
            module.fail_json(msg=str(e), changed=False)


if __name__ == '__main__':
    main()
