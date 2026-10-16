package main

import (
	"fmt"

	"gopanel/appmenu"
)

func main() {
	cats, all, err := appmenu.Load()
	if err != nil {
		panic(err)
	}
	fmt.Printf("%d categories, %d apps\n", len(cats), len(all))
	for _, c := range cats {
		fmt.Printf("%-14s icon=%-28s %d apps\n", c.Name, c.Icon, len(c.Entries))
		for i, e := range c.Entries {
			if i < 4 {
				fmt.Printf("    %s | %s | %s\n", e.Name, e.GenericName, e.Comment)
			}
		}
	}
}
