import matplotlib.pyplot as plt

import draw_function as draw



def main() -> None:
    """Run all plotting pipelines and display generated figures."""
    draw.accelerator()
    draw.LFP()
    plt.show()


if __name__ == "__main__":
    main()
