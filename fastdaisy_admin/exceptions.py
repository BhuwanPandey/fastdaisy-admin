class FastDaisyAdminException(Exception):
    pass


class InvalidModelError(FastDaisyAdminException):
    pass


class NoConverterFound(FastDaisyAdminException):
    pass
