variable "GO_VERSION" {
  default = "1.27.0"
}

variable "ALPINE_VERSION" {
  default = "3.24"
}

target "builder" {
  dockerfile = "docker/base/Dockerfile.builder"
  args = {
    ALPINE_VERSION = ALPINE_VERSION
  }
  tags = ["quantum-safe-builder:latest"]
  output = ["type=docker"]
}

target "runtime" {
  dockerfile = "docker/base/Dockerfile.runtime"
  args = {
    ALPINE_VERSION = ALPINE_VERSION
  }
  tags = ["quantum-safe-runtime:latest"]
  output = ["type=docker"]
}

target "radius" {
  dockerfile = "docker/radius/Dockerfile"
  contexts = {
    builder = "target:builder"
    runtime = "target:runtime"
  }
  tags = ["quantum-safe-radius:latest"]
  output = ["type=docker"]
}

target "syslog" {
  dockerfile = "docker/syslog/Dockerfile"
  contexts = {
    builder = "target:builder"
    runtime = "target:runtime"
  }
  tags = ["quantum-safe-syslog:latest"]
  output = ["type=docker"]
}

target "kme" {
  dockerfile = "docker/kme/Dockerfile"
  contexts = {
    runtime = "target:runtime"
  }
  tags = ["quantum-safe-kme:latest"]
  output = ["type=docker"]
}

target "test-runner" {
  dockerfile = "docker/test-runner/Dockerfile"
  contexts = {
    runtime = "target:runtime"
  }
  args = {
    GO_VERSION = GO_VERSION
    ALPINE_VERSION = ALPINE_VERSION
  }
  tags = ["quantum-safe-test-runner:latest"]
  output = ["type=docker"]
}

group "default" {
  targets = ["builder", "runtime", "radius", "syslog", "kme", "test-runner"]
}
