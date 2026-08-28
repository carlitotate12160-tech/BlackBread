class LedgerError(RuntimeError):
    pass


class LedgerAccessError(LedgerError):
    pass


class LedgerValidationError(LedgerError, ValueError):
    pass
