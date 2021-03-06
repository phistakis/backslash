import Ember from "ember";
import ComplexModelRoute from "../../mixins/complex-model-route";

export default Ember.Route.extend(ComplexModelRoute, {
  api: Ember.inject.service(),

  model() {
    let self = this;
    let session_model = this.modelFor("session").session_model;
    return Ember.RSVP.hash({
      session_model: session_model,
      related_entities: self.store.query('entity', {session_id: session_model.id, page_size: 100}),
      metadata: this.get("api")
        .call("get_metadata", {
          entity_type: "session",
          entity_id: parseInt(session_model.id)
        })
        .then(
          function(r)
          {
            if (session_model.data.child_id != null) {
              delete r.result['slash::commandline'];
            }
            return r.result;
          }
        )
    });
  }
});
