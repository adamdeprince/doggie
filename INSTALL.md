# Install Silkie

Follow the [Silkie installation guide](html/install.html) for prerequisites,
source builds, and running the terminal. Build from the
[`silkie` branch](https://github.com/adamdeprince/silkie/tree/silkie):

```sh
git clone --branch silkie https://github.com/adamdeprince/silkie.git
cd silkie
./dev.sh build
./kitty/launcher/kitty
```

The executable retains the name `kitty`. Upstream kitty packages provide
upstream kitty; build this repository to get Silkie's extensions.
