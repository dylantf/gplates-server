# https://zenodo.org/records/10659112

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

        pythonEnv = python.withPackages (ps: [
          pygplates
          ps.numpy
          ps.netcdf4
          ps.matplotlib
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
            export GPLATES_MODEL_DIR="$PWD/models/paleomap"
            export PORT=8080
          '';
        };

        packages.default = pythonEnv;
      }
    );
}
