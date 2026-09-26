from slogger import builtin_logger, instrument


@instrument(capture=["numerator", "denominator"])
def divide_two_floats(numerator: float, denominator: float) -> float:
    if denominator == 0:
        raise ZeroDivisionError("denominator must not be 0")

    result = float(numerator) / float(denominator)
    builtin_logger.debug("Division Successful", result=result)

    return result


def main():
    builtin_logger.info("Program to add numbers")

    try:
        result = divide_two_floats(5, 2)
        builtin_logger.info(f"result {result}", result=result)
    except Exception:
        builtin_logger.exception("Exception while division")

    try:
        result = divide_two_floats(5, 0)
        builtin_logger.info(f"result {result}", result=result)
    except Exception:
        builtin_logger.exception("Exception while division")


if __name__ == "__main__":
    main()
