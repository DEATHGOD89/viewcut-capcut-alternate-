from setuptools import setup, find_packages

setup(
    name="video-editor-lite",
    version="1.0.0",
    description="Lightweight Video Editor",
    author="Your Name",
    packages=find_packages(),
    install_requires=[
        'PySide6>=6.5.0',
        'ffmpeg-python>=0.2.0',
        'numpy>=1.24.0',
        'pillow>=10.0.0',
        'psutil>=5.9.0',
    ],
    entry_points={
        'console_scripts': [
            'video-editor-lite=src.main:main',
        ],
    },
    python_requires='>=3.8',
)
