from setuptools import setup

setup(
    name='foreman-dlm-updater',
    version='0.0.2',
    description='ForemanDlmUpdater, Linux client counterpart to the awesome Foreman DLM plugin.',
    long_description="""
foreman-dlm-updater is a helper script that allows to do graceful, rolling updates on clustered Linux systems.

Copyright (c) 2018, Stephan Schultchen.

License: MIT (see LICENSE for details)
    """,
    packages=['foreman_dlm_updater'],
    scripts=[
        'contrib/foreman_dlm_updater',
    ],
    url='https://github.com/schlitzered/foreman_dlm_updater',
    license='MIT',
    author='schlitzer',
    author_email='stephan.schultchen@gmail.com',
    test_suite='test',
    platforms='posix',
    classifiers=[
            'License :: OSI Approved :: MIT License',
            'Programming Language :: Python :: 3'
    ],
    setup_requires=[
        'pep3143daemon',
        'requests'
    ],
    install_requires=[
        'pep3143daemon',
        'requests'
    ],
    keywords=[
        'foreman', 'dlm',
    ]
)
