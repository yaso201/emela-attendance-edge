from setuptools import find_packages, setup

setup(
    name="attendance_edge",
    version="0.0.1",
    description="LaNEM attendance edge capture app",
    author="SI LaNEM",
    author_email="devnull@lanem.local",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=[],
)
