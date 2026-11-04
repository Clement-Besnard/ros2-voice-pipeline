from setuptools import find_packages, setup

package_name = 'voice_pipeline'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Clément Besnard',
    maintainer_email='clementbesnard24@gmail.com',
    description='Pipeline vocal micro -> LLM -> TTS',
    license='MIT',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'echo_node = voice_pipeline.echo_node:main',
            'llm_node = voice_pipeline.llm_node:main',
        ],
    },
)
