import { describe, expect, it } from "vitest";
import { mergeRequestedNodes } from "./workflowDraft";

const base = {
  nodes: [
    {
      id: 51, type: "DanbooruGalleryNode", pos: [10, 20], size: [300, 400], order: 2,
      widgets_values: ["old"], properties: { selection_data: "old" }, custom_state: { prompt: "old" },
      inputs: [{ name: "image", link: 99, widget: { name: "image" } }],
      outputs: [{ name: "IMAGE", links: [100] }],
    },
    { id: 88, type: "SaveImage", widgets_values: ["keep"] },
  ],
  links: [[99, 1, 0, 51, 0, "IMAGE"]],
  groups: [{ title: "group" }],
};

describe("mergeRequestedNodes", () => {
  it("updates dynamic state while preserving full graph topology", () => {
    const update = {
      node: {
        id: 51, type: "Wrong", pos: [0, 0], size: [1, 1], order: 9,
        widgets_values: ["new"], properties: { selection_data: "new" }, custom_state: { prompt: "new" },
        inputs: [{ name: "image", link: null, widget: { name: "image", value: "new.png" } }],
        outputs: [{ name: "IMAGE", links: null, custom: "new-output" }],
      },
    };
    const result: any = mergeRequestedNodes(base, [update]);
    const node = result.nodes[0];
    expect(node).toMatchObject({
      id: 51, type: "DanbooruGalleryNode", pos: [10, 20], size: [300, 400], order: 2,
      widgets_values: ["new"], properties: { selection_data: "new" }, custom_state: { prompt: "new" },
    });
    expect(node.inputs[0]).toMatchObject({ link: 99, widget: { name: "image", value: "new.png" } });
    expect(node.outputs[0]).toMatchObject({ links: [100], custom: "new-output" });
    expect(result.links).toEqual(base.links);
    expect(result.groups).toEqual(base.groups);
    expect(result.nodes[1]).toEqual(base.nodes[1]);
    expect((base.nodes[0] as any).properties.selection_data).toBe("old");
  });

  it("uses the previous draft as the next merge base", () => {
    const first: any = mergeRequestedNodes(base, [{ node: { id: 51, custom_state: { prompt: "first" } } }]);
    const second: any = mergeRequestedNodes(first, [{ node: { id: 51, properties: { selection_data: "second" } } }]);
    expect(second.nodes[0].custom_state.prompt).toBe("first");
    expect(second.nodes[0].properties.selection_data).toBe("second");
  });

  it("ignores missing nodes and null responses", () => {
    expect(mergeRequestedNodes(base, [null, { node: { id: 999, widgets_values: ["x"] } }])).toEqual(base);
  });
});
