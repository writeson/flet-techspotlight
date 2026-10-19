import flet as ft

from database import load_hotspots_text


async def main(page: ft.Page):
    counter = ft.Text("0", size=50, data=0)

    def increment_click(e: ft.Event[ft.FloatingActionButton]):
        counter.data += 1
        counter.value = str(counter.data)

    hotspots = ft.Text("loading hotspot data…", size=14, italic=True)

    page.floating_action_button = ft.FloatingActionButton(
        icon=ft.Icons.ADD, key="increment", on_click=increment_click
    )
    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Container(
                content=ft.Column(
                    [
                        counter,
                        hotspots,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=24,
                ),
                alignment=ft.Alignment.CENTER,
            ),
        )
    )
    hotspots.value = await load_hotspots_text()
    page.update()


if __name__ == "__main__":
    ft.run(main)
