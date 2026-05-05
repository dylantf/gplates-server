{
  description = "pygplates dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;

        pygplates = python.pkgs.buildPythonPackage rec {
          pname = "pygplates";
          version = "1.0.0";
          format = "wheel";

          src = pkgs.fetchurl {
            url = "https://files.pythonhosted.org/packages/02/e1/bd5d784d82d42898cb0171171a82bd1a2de9691055b3719b2b0c7444babf/pygplates-${version}-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl";
            hash = "sha256-BQCF+JsWj2C38VDpZNftL4zWNJu05GENn1GQh/ohGBo=";
          };

          nativeBuildInputs = [ pkgs.autoPatchelfHook ];

          buildInputs = with pkgs; [
            stdenv.cc.cc.lib # libstdc++
            zlib
            glib
            libGL
            expat
          ];

          propagatedBuildInputs = [ python.pkgs.numpy ];

          # manylinux wheels bundle their own deps under pygplates/lib;
          # let autoPatchelf find them.
          autoPatchelfIgnoreMissingDeps = true;

          pythonImportsCheck = [ "pygplates" ];
        };

        plate-model-manager = python.pkgs.buildPythonPackage rec {
          pname = "plate-model-manager";
          version = "1.3.1";
          format = "wheel";

          src = pkgs.fetchurl {
            url = "https://files.pythonhosted.org/packages/36/4d/2cd5fba9789197c3c9c3bfd3691389913712f261e70910c7e5104d9420f8/plate_model_manager-${version}-py3-none-any.whl";
            hash = "sha256-wRWDISTz6GdV+9kFwaL1UjZ6CuiKcqha0Z8FCA9Dg94=";
          };

          propagatedBuildInputs = with python.pkgs; [
            aiohttp
            requests
            nest-asyncio
          ];

          pythonImportsCheck = [ "plate_model_manager" ];
        };

        antimeridian = python.pkgs.buildPythonPackage rec {
          pname = "antimeridian";
          version = "0.4.7";
          format = "wheel";

          src = pkgs.fetchurl {
            url = "https://files.pythonhosted.org/packages/50/cc/f1f8a798820dfa339f8321e3b92f5cda38b0e4b2a0bd38f9d7a64bca26ca/antimeridian-${version}-py3-none-any.whl";
            hash = "sha256-/twE1UYO6fBeN+etwzWENTj72RHCv3vTbFOTzU/+EH0=";
          };

          propagatedBuildInputs = with python.pkgs; [
            numpy
            shapely
          ];

          pythonImportsCheck = [ "antimeridian" ];
        };

        pythonEnv = python.withPackages (ps: [
          pygplates
          plate-model-manager
          antimeridian
          ps.numpy
        ]);
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            pythonEnv
            pkgs.bun
          ];

          shellHook = ''
            export GPLATES_PYTHON="$(command -v python)"
            export GPLATES_MODEL_DIR="$PWD/models/muller2022"
            export PORT=8080
          '';
        };

        packages.default = pythonEnv;
      }
    );
}
