from distutils.core import setup

setup(name='aar2slob',
      version='1.0',
      description='Aard Dictionary to slob converter',
      author='Igor Tkach',
      author_email='itkach@gmail.com',
      url='http://github.com/itkach/aar2slob',
      license='GPL3',
      packages=['aar2slob'],
      package_data={'aar2slob': ['*.css']},
      install_requires=['Slob >= 1.0', 'BeautifulSoup4'])
