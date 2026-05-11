import webapp


def test_package_exposes_version():
    assert webapp.__version__ == "0.1.0"
