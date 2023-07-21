FROM registry.fedoraproject.org/fedora:latest

RUN dnf update -y && \
  dnf install -y make git gettext-devel autoconf automake bison gettext gperf m4 texinfo texinfo-tex patch wget xz gcc

RUN git clone git://git.sv.gnu.org/coreutils
WORKDIR /coreutils

ENV FORCE_UNSAFE_CONFIGURE=1
ENV RUN_VERY_EXPENSIVE_TESTS=yes

RUN ./bootstrap
RUN ./configure --quiet --disable-gcc-warnings
RUN make
