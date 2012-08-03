import time

import sqlaload as sl
import nkclient as nk

from common import *
from common import issue as _issue

log = logging.getLogger('combine')
KEY_CACHE = {}

def issue(engine, resource_id, resource_hash, message, data={}):
    _issue(engine, resource_id, resource_hash, 'combine',
           message, data=data)

def normalize(column_name):
    column_name = column_name.replace('.', '')
    column_name = column_name.replace(',', '')
    column_name = column_name.replace('  ', ' ')
    column_name = column_name.replace('no.', 'Number')
    column_name = column_name.replace('No.', 'Number')
    return column_name.strip()

def normalize_hard(column_name):
    column_name = normalize(column_name)
    column_name = column_name.replace('_', '')
    column_name = column_name.replace('-', '')
    column_name = column_name.lower().replace(' ', '')
    return {
        'amount': 'Amount',
        'amountinsterling': 'Amount',
        'gross': 'Amount',
        'departmentfamily': 'DepartmentFamilyName',
        'departmentalfamily': 'DepartmentFamilyName',
        'deptfamily': 'DepartmentFamilyName',
        'date': 'Date',
        'dateofpayment': 'Date',
        'paymentdate': 'Date',
        'transactiondate': 'Date',
        'entity': 'EntityName',
        'transactionnumber': 'TransactionNumber',
        'transactionnr': 'TransactionNumber',
        'transactionno': 'TransactionNumber',
        'transno': 'TransactionNumber',
        'expensearea': 'ExpenseArea',
        'expensesarea': 'ExpenseArea',
        'expensetype': 'ExpenseType',
        'expensestype': 'ExpenseType',
        'expendituretype': 'ExpenditureType',
        'supplier': 'SupplierName',
        'suppliername': 'SupplierName',
        'suppliertype': 'SupplierType',
        'vatregistrationnumber': 'SupplierVATNumber',
        'supplierpostcode': 'SupplierPostalCode',
        'projectcode': 'ProjectCode'
        }.get(column_name)

def column_mapping(row, columns):
    nkc = nk_connect('uk25k-column-names')
    columns.remove('id')
    sheet_signature = '|'.join(sorted(set(map(normalize, columns))))
    mapping = {}
    failed = False
    for column in columns:
        if column.startswith("column_"):
            mapping[column] = None
            continue
        try:
            key = normalize_hard(column)
            if key is not None:
                mapping[column] = key
                continue
            key = '%s @ [%s]' % (normalize(column), sheet_signature)
            if key in KEY_CACHE:
                mapping[column] = KEY_CACHE[key]
                continue
            try:
                v = nkc.lookup(key)
                mapping[column] = v.value
            except nk.NKInvalid, nm:
                mapping[column] = None
            except nk.NKNoMatch, nm:
                failed = True
            KEY_CACHE[key] = mapping.get(column)
        except Exception, e:
            log.exception(e)
            failed = True
            mapping[column] = None
    if not len([(k,v) for k,v in mapping.items() if v is not None]):
        return None
    return None if failed else mapping

def combine_sheet(engine, resource, sheet_id, table, mapping):
    begin = time.time()
    base = {
            'resource_id': resource['resource_id'],
            'resource_hash': resource['extract_hash'],
            'sheet_id': sheet_id,
        }
    spending_table = sl.get_table(engine, 'spending')
    connection = engine.connect()
    trans = connection.begin()
    try:
        rows = 0
        sl.delete(connection, spending_table,
                resource_id=resource['resource_id'],
                sheet_id=sheet_id)
        for row in sl.all(connection, table):
            data = dict(base)
            for col, value in row.items():
                if col == 'id':
                    data['row_id'] = value
                    continue
                mapped = mapping.get(col)
                if mapped is not None:
                    data[mapped] = value
            sl.add_row(connection, spending_table, data)
            rows += 1
        trans.commit()
        log.info("Loaded %s rows in %s ms", rows,
                int((time.time()-begin)*1000))
        return rows > 0
    finally:
        connection.close()

def combine_resource_core(engine, row):
    success = True
    for sheet_id in range(0, row['sheets']):
        table = sl.get_table(engine, 'raw_%s_sheet%s' % (
            row['resource_id'], sheet_id))
        if not engine.has_table(table.name):
            log.warn("Sheet table does not exist: %s", table)
            success = False
            continue
        columns = [c.name for c in table.columns]
        mapping = column_mapping(row, columns)
        if mapping is None:
            log.warn("Unable to generate mapping: %r", columns)
            success = False
            continue
        if not combine_sheet(engine, row, sheet_id, table, mapping):
            succces = False
    return success

def combine_resource(engine, source_table, row, force):
    if not row['extract_status']:
        return

    # Skip over tables we have already combined
    if not force and sl.find_one(engine, source_table,
            resource_id=row['resource_id'],
            combine_hash=row['extract_hash'],
            combine_status=True) is not None:
        return

    log.info("Combine: %s, Resource %s", row['package_name'], row['resource_id'])

    status = combine_resource_core(engine, row)
    sl.upsert(engine, source_table, {
        'resource_id': row['resource_id'],
        'combine_hash': row['extract_hash'],
        'combine_status': status,
        }, unique=['resource_id'])

def combine_all(force=False):
    engine = db_connect()
    source_table = sl.get_table(engine, 'source')
    for row in sl.find(engine, source_table):
        combine_resource(engine, source_table, row, force)

if __name__ == '__main__':
    combine_all(False)

